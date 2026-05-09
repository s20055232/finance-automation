"""
extractor.py — Phase 1：從 PDF / CSV 擷取發票資料

=== RPA 概念說明 ===
傳統 RPA 機器人用「螢幕錄製」模擬人類點擊來取得資料。
這個模組展示的是「第四代 RPA」：直接解析非結構化資料（PDF 文字、表格）
取代人工閱讀，不需要 UI 自動化。

處理順序（每張 PDF）：
    1. 用 pdfplumber 提取所有頁面的文字與表格
    2. 優先從表格擷取明細（結構化，準確度高）
    3. 若表格擷取失敗，改用 regex 解析純文字（fallback）
    4. 用 regex 從文字中找發票號碼、廠商、日期、總金額
    5. 組裝成 InvoiceData 回傳給下一個 Phase
"""

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pdfplumber

from src.models import InvoiceData, LineItem

# ── Regex 模式（定義在模組頂部，方便閱讀與維護）────────────────────────────

INVOICE_NUMBER_RE = re.compile(
    r"(?:Invoice\s*(?:No\.?|#|Number)|INV|Bill\s*#?|Receipt\s*#?)"
    r"[\s:#]*([A-Z0-9][A-Z0-9\-/]{2,})",
    re.IGNORECASE,
)

VENDOR_RE = re.compile(
    r"(?:From|Vendor|Billed?\s*By|Supplier|Company)[\s:]+(.+?)(?:\n|$)",
    re.IGNORECASE,
)

DATE_RE = re.compile(
    r"(?:Invoice\s*Date|Date|Dated|Issued)[\s:]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
    r"|\w+\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)

TOTAL_RE = re.compile(
    r"(?:Total\s*Due|Grand\s*Total|Amount\s*Due|Total\s*Amount|TOTAL)"
    r"[\s:$]*(\d[\d,]*\.?\d{0,2})",
    re.IGNORECASE,
)

AMOUNT_RE = re.compile(r"\$?\s*(\d[\d,]*\.?\d{0,2})")

# 表格標頭的可能關鍵字（用來找到明細表格）
ITEM_HEADER_KEYWORDS = {"description", "item", "service", "product", "detail"}
QTY_KEYWORDS = {"qty", "quantity", "units", "count"}
PRICE_KEYWORDS = {"price", "rate", "unit price", "unit cost"}
AMOUNT_KEYWORDS = {"amount", "total", "line total", "subtotal"}


# ── 公開介面 ──────────────────────────────────────────────────────────────────

def extract_from_file(filepath: Path) -> InvoiceData:
    """
    根據副檔名分派到對應的擷取函式。
    支援：.pdf、.csv、.xlsx、.xls
    """
    suffix = filepath.suffix.lower()
    if suffix == ".pdf":
        return extract_from_pdf(filepath)
    if suffix == ".csv":
        return extract_from_csv(filepath)
    if suffix in {".xlsx", ".xls"}:
        return extract_from_excel(filepath)
    raise ValueError(f"不支援的檔案格式：{suffix}")


def scan_folder(folder: Path) -> list[InvoiceData]:
    """
    掃描資料夾，處理所有支援的發票檔案。
    解析失敗的檔案只印出警告，不中斷整個流程。
    """
    supported = {".pdf", ".csv", ".xlsx", ".xls"}
    results = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in supported:
            continue
        try:
            results.append(extract_from_file(path))
        except Exception as e:
            print(f"  [WARNING] 跳過 {path.name}：{e}")
    return results


# ── PDF 擷取 ──────────────────────────────────────────────────────────────────

def extract_from_pdf(filepath: Path) -> InvoiceData:
    full_text = ""
    all_tables = []

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text += text + "\n"
            tables = page.extract_tables()
            if tables:
                all_tables.extend(tables)

    header = _parse_header(full_text)

    # 優先用表格取明細，失敗再用文字 regex
    line_items = _parse_items_from_tables(all_tables)
    if not line_items:
        line_items = _parse_items_from_text(full_text)

    subtotal = sum(i.amount for i in line_items)
    total = header.get("total") or subtotal
    tax = max(0.0, total - subtotal)

    confidence = _assess_confidence(header, line_items, total)

    return InvoiceData(
        invoice_number=header.get("invoice_number") or f"UNKNOWN-{filepath.stem}",
        vendor_name=header.get("vendor") or filepath.stem,
        invoice_date=header.get("date") or "",
        due_date=header.get("due_date"),
        line_items=line_items,
        subtotal=subtotal,
        tax_amount=tax,
        total_amount=total,
        currency="USD",
        source_file=filepath.name,
        extraction_method="pdf_text",
        raw_text=full_text[:2000],   # 保留前 2000 字給 AI 分類參考
        extraction_confidence=confidence,
    )


def extract_from_csv(filepath: Path) -> InvoiceData:
    """
    解析 CSV 發票。
    期望欄位：invoice_number, vendor_name, invoice_date, description, quantity, unit_price
    欄位名稱不區分大小寫，也接受 vendor / qty / price 等縮寫。
    """
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError(f"{filepath.name} 是空的 CSV")

    # 正規化欄位名稱（小寫 + 去空格）
    def norm(key: str) -> str:
        return key.lower().strip()

    first = {norm(k): v for k, v in rows[0].items()}

    def get(row: dict, *candidates: str) -> str:
        d = {norm(k): v for k, v in row.items()}
        for c in candidates:
            if c in d:
                return (d[c] or "").strip()
        return ""

    invoice_number = get(rows[0], "invoice_number", "invoice_no", "inv_number")
    vendor_name = get(rows[0], "vendor_name", "vendor", "supplier", "company")
    invoice_date = _normalize_date(get(rows[0], "invoice_date", "date"))

    line_items = []
    for row in rows:
        desc = get(row, "description", "item", "service", "product")
        qty = _to_float(get(row, "quantity", "qty", "units"))
        price = _to_float(get(row, "unit_price", "price", "rate", "unit_cost"))
        amount = _to_float(get(row, "amount", "total", "line_total"))
        if not amount and qty and price:
            amount = qty * price
        if desc or amount:
            line_items.append(LineItem(
                description=desc,
                quantity=qty or 1.0,
                unit_price=price or amount,
                amount=amount,
            ))

    subtotal = sum(i.amount for i in line_items)
    return InvoiceData(
        invoice_number=invoice_number or f"CSV-{filepath.stem}",
        vendor_name=vendor_name or filepath.stem,
        invoice_date=invoice_date,
        due_date=None,
        line_items=line_items,
        subtotal=subtotal,
        tax_amount=0.0,
        total_amount=subtotal,
        currency="USD",
        source_file=filepath.name,
        extraction_method="csv",
        raw_text=None,
        extraction_confidence="high" if (invoice_number and vendor_name) else "medium",
    )


def extract_from_excel(filepath: Path) -> InvoiceData:
    """Excel 版本：用 pandas 讀取後轉成與 CSV 相同的格式。"""
    import pandas as pd
    df = pd.read_excel(filepath, dtype=str).fillna("")
    # 轉成 list[dict] 後重用 CSV 解析邏輯
    with open(filepath.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        df.to_csv(f, index=False)
    return extract_from_csv(filepath.with_suffix(".csv"))


# ── 內部解析函式 ──────────────────────────────────────────────────────────────

def _parse_header(text: str) -> dict:
    """從 PDF 純文字中用 regex 提取發票基本資訊。"""
    result: dict = {}

    m = INVOICE_NUMBER_RE.search(text)
    if m:
        result["invoice_number"] = m.group(1).strip()

    m = VENDOR_RE.search(text)
    if m:
        result["vendor"] = m.group(1).strip()[:80]

    m = DATE_RE.search(text)
    if m:
        result["date"] = _normalize_date(m.group(1))

    # 找最後一個 TOTAL（通常是 Grand Total）
    totals = TOTAL_RE.findall(text)
    if totals:
        result["total"] = _to_float(totals[-1])

    return result


def _parse_items_from_tables(tables: list) -> list[LineItem]:
    """
    從 pdfplumber 提取的表格中找明細行。
    策略：找包含 Description / Amount 關鍵字的表格，然後逐行解析。
    """
    for table in tables:
        if not table or len(table) < 2:
            continue

        header_row = [str(cell or "").lower().strip() for cell in table[0]]
        desc_col = _find_col(header_row, ITEM_HEADER_KEYWORDS)
        amt_col = _find_col(header_row, AMOUNT_KEYWORDS)

        if desc_col is None or amt_col is None:
            continue

        qty_col = _find_col(header_row, QTY_KEYWORDS)
        price_col = _find_col(header_row, PRICE_KEYWORDS)

        items = []
        for row in table[1:]:
            if not row or all(not cell for cell in row):
                continue
            desc = str(row[desc_col] or "").strip()
            amount = _to_float(str(row[amt_col] or ""))
            qty = _to_float(str(row[qty_col] or "")) if qty_col is not None else 1.0
            price = _to_float(str(row[price_col] or "")) if price_col is not None else amount

            # 跳過小計 / 合計行
            if any(kw in desc.lower() for kw in ("total", "subtotal", "tax", "due")):
                continue
            if desc and amount:
                items.append(LineItem(desc, qty or 1.0, price or amount, amount))

        if items:
            return items

    return []


def _parse_items_from_text(text: str) -> list[LineItem]:
    """
    Fallback：用 regex 從純文字中解析明細行。
    匹配形如 "MacBook Pro 14-inch  2  $1,999.00  $3,998.00" 的行。
    """
    items = []
    lines = text.split("\n")
    for line in lines:
        amounts = AMOUNT_RE.findall(line)
        if len(amounts) < 1:
            continue

        # 最後一個金額視為該行的 amount
        amount = _to_float(amounts[-1])
        if amount < 0.01:
            continue

        # 用 regex 把金額部分去掉，剩下的當作 description
        desc = re.sub(r"\$?\s*[\d,]+\.?\d*", "", line).strip()
        desc = re.sub(r"\s+", " ", desc).strip()

        if not desc or any(kw in desc.lower() for kw in ("total", "subtotal", "tax")):
            continue

        items.append(LineItem(
            description=desc[:100],
            quantity=1.0,
            unit_price=amount,
            amount=amount,
        ))

    return items[:20]   # 最多取 20 行，避免誤解析雜訊


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _find_col(header: list[str], keywords: set[str]) -> Optional[int]:
    """在表格標頭中找到符合關鍵字的欄位索引。"""
    for i, h in enumerate(header):
        if any(kw in h for kw in keywords):
            return i
    return None


def _normalize_date(date_str: str) -> str:
    """
    把各種日期格式統一轉成 ISO 格式（YYYY-MM-DD）。
    例：'January 15, 2024' → '2024-01-15'
        '01/15/2024'       → '2024-01-15'
    """
    if not date_str:
        return ""
    formats = [
        "%B %d, %Y", "%B %d %Y",       # January 15, 2024
        "%b %d, %Y", "%b %d %Y",       # Jan 15, 2024
        "%m/%d/%Y", "%d/%m/%Y",        # 01/15/2024 或 15/01/2024
        "%Y-%m-%d",                    # 已是 ISO 格式
        "%m-%d-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()   # 解析失敗，原樣回傳


def _to_float(value: str) -> float:
    """把 '$1,234.56' 這類字串轉成 float 1234.56。"""
    if not value:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _assess_confidence(header: dict, items: list, total: float) -> str:
    """評估擷取品質。"""
    score = 0
    if header.get("invoice_number"):
        score += 1
    if header.get("vendor"):
        score += 1
    if header.get("date"):
        score += 1
    if items:
        score += 1
    if total > 0:
        score += 1

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"
