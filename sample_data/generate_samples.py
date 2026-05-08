"""
generate_samples.py — 產生範例發票 PDF 與 CSV

產生 7 份測試用發票：
  6 張 PDF（模擬從 Email 或資料夾收到的供應商發票）
  1 份 CSV（模擬從 ERP 系統匯出的發票資料）

其中 INV-2024-001 出現兩次（不同日期、不同數量）
→ 故意製造「重複請款」異常，展示 AI Bot 的異常偵測能力。

運行方式：
    uv run python sample_data/generate_samples.py
"""

import csv
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph, HRFlowable
)
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

OUTPUT_DIR = Path(__file__).parent / "invoices"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 顏色定義 ──────────────────────────────────────────────────────────────────
DARK_BLUE  = colors.HexColor("#1F4E79")
LIGHT_BLUE = colors.HexColor("#D6E4F7")
MID_BLUE   = colors.HexColor("#2E75B6")
LIGHT_GRAY = colors.HexColor("#F2F2F2")

# ── 6 張 PDF 發票的資料 ────────────────────────────────────────────────────────
# 每張發票模擬不同廠商、不同費用類別
# 最後一筆（INV-2024-001_DUPLICATE）是故意重複的，供展示異常偵測
SAMPLE_INVOICES = [
    {
        "filename": "INV-2024-001_acme_tech.pdf",
        "invoice_number": "INV-2024-001",
        "vendor_name": "Acme Technology Solutions",
        "vendor_address": "123 Silicon Valley Blvd, San Jose, CA 95110",
        "bill_to": "Your Company Inc.",
        "invoice_date": "January 15, 2024",
        "due_date": "February 15, 2024",
        "items": [
            # 電腦設備 → AI 應分類為 equipment
            ("MacBook Pro 14-inch M3 Pro", 2, 1999.00),
            ("USB-C Hub 10-in-1",          2,   49.99),
            ("AppleCare+ (2-year)",         2,  249.00),
        ],
        "tax_rate": 0.08,
        "notes": "Net 30. Payment by bank transfer preferred.",
    },
    {
        "filename": "INV-2024-002_downtown_office.pdf",
        "invoice_number": "INV-2024-002",
        "vendor_name": "Downtown Office Spaces LLC",
        "vendor_address": "888 Business Park Ave, Chicago, IL 60601",
        "bill_to": "Your Company Inc.",
        "invoice_date": "January 1, 2024",
        "due_date": "January 5, 2024",
        "items": [
            # 辦公室租金 → AI 應分類為 rent
            ("Office Rent - Suite 501, January 2024",   1, 3500.00),
            ("Parking Space x2 - January 2024",         1,  240.00),
            ("Building Maintenance Fee - January 2024", 1,   60.00),
        ],
        "tax_rate": 0.0,
        "notes": "Please reference lease agreement #LA-2023-88.",
    },
    {
        "filename": "INV-2024-003_digital_marketing.pdf",
        "invoice_number": "INV-2024-003",
        "vendor_name": "Digital Marketing Agency Co.",
        "vendor_address": "55 Madison Ave, New York, NY 10022",
        "bill_to": "Your Company Inc.",
        "invoice_date": "January 20, 2024",
        "due_date": "February 20, 2024",
        "items": [
            # 廣告行銷 → AI 應分類為 marketing
            ("Google Ads Campaign Management - Jan",  1, 1200.00),
            ("SEO Optimization & Monthly Report",     1,  800.00),
            ("Social Media Content (4 posts/week)",   4,  250.00),
            ("Email Newsletter Design x2",            2,  150.00),
        ],
        "tax_rate": 0.0,
        "notes": "Campaign performance report attached separately.",
    },
    {
        "filename": "INV-2024-004_city_power.pdf",
        "invoice_number": "INV-2024-004",
        "vendor_name": "City Power & Light Co.",
        "vendor_address": "PO Box 9000, Chicago, IL 60690",
        "bill_to": "Your Company Inc.",
        "invoice_date": "January 28, 2024",
        "due_date": "February 12, 2024",
        "items": [
            # 水電費 → AI 應分類為 utilities
            ("Electricity Usage - January 2024 (3,250 kWh)", 1, 487.50),
            ("Late Payment Fee",                              1,  12.00),
        ],
        "tax_rate": 0.0,
        "notes": "Account #: 4521-8890-01. Auto-pay available.",
    },
    {
        "filename": "INV-2024-005_cloudstack.pdf",
        "invoice_number": "INV-2024-005",
        "vendor_name": "CloudStack Inc.",
        "vendor_address": "410 Terry Ave N, Seattle, WA 98109",
        "bill_to": "Your Company Inc.",
        "invoice_date": "January 1, 2024",
        "due_date": "January 1, 2024",
        "items": [
            # 軟體/SaaS → AI 應分類為 software
            ("AWS Infrastructure - Monthly (Jan 2024)",      1, 2340.00),
            ("Slack Business License (50 seats x $12.50)",  50,   12.50),
            ("GitHub Enterprise (10 seats x $21)",          10,   21.00),
        ],
        "tax_rate": 0.0,
        "notes": "Auto-charged to card ending 4242. Usage report in AWS Console.",
    },
    {
        # 故意重複：同一廠商 Acme Tech，發票號碼相同，日期和數量不同
        # 模擬「供應商重複請款」的真實異常場景
        "filename": "INV-2024-001_acme_tech_DUPLICATE.pdf",
        "invoice_number": "INV-2024-001",
        "vendor_name": "Acme Technology Solutions",
        "vendor_address": "123 Silicon Valley Blvd, San Jose, CA 95110",
        "bill_to": "Your Company Inc.",
        "invoice_date": "January 16, 2024",
        "due_date": "February 16, 2024",
        "items": [
            ("MacBook Pro 14-inch M3 Pro", 1, 1999.00),
        ],
        "tax_rate": 0.08,
        "notes": "Revised invoice. Please discard previous version.",
    },
]


def _build_pdf(data: dict, output_path: Path) -> None:
    """用 ReportLab 產生一張專業外觀的發票 PDF。"""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=15 * mm,  bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    story  = []

    # Header：廠商名稱 + INVOICE 標題
    header_data = [[
        Paragraph(
            f'<font color="#FFFFFF"><b>{data["vendor_name"]}</b></font><br/>'
            f'<font color="#AACCFF" size="8">{data["vendor_address"]}</font>',
            ParagraphStyle("vendor", fontSize=11, leading=16),
        ),
        Paragraph(
            '<font color="#FFFFFF" size="22"><b>INVOICE</b></font>',
            ParagraphStyle("title", fontSize=22, alignment=TA_RIGHT),
        ),
    ]]
    ht = Table(header_data, colWidths=[110 * mm, 60 * mm])
    ht.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), DARK_BLUE),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(ht)
    story.append(Spacer(1, 6 * mm))

    # 發票基本資訊
    info_data = [[
        Paragraph(f"<b>Bill To:</b><br/>{data['bill_to']}", styles["Normal"]),
        Table(
            [
                ["Invoice #:",    data["invoice_number"]],
                ["Invoice Date:", data["invoice_date"]],
                ["Due Date:",     data["due_date"]],
            ],
            colWidths=[35 * mm, 45 * mm],
            style=TableStyle([
                ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 9),
                ("ALIGN",         (1, 0), (1, -1), "LEFT"),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]),
        ),
    ]]
    it = Table(info_data, colWidths=[90 * mm, 80 * mm])
    it.setStyle(TableStyle([
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (1, 0), (1, 0),  LIGHT_GRAY),
        ("BOX",        (1, 0), (1, 0),  0.5, colors.lightgrey),
    ]))
    story.append(it)
    story.append(Spacer(1, 6 * mm))

    # 項目明細
    subtotal  = 0.0
    item_rows = []
    for desc, qty, unit_price in data["items"]:
        amount    = qty * unit_price
        subtotal += amount
        item_rows.append([desc, str(qty), f"${unit_price:,.2f}", f"${amount:,.2f}"])

    items_data = [["Description", "Qty", "Unit Price", "Amount"]] + item_rows
    items_t    = Table(items_data, colWidths=[95 * mm, 15 * mm, 30 * mm, 30 * mm])
    row_styles = [
        ("BACKGROUND",    (0, 0), (-1, 0),  DARK_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.lightgrey),
    ]
    for i in range(1, len(items_data)):
        if i % 2 == 0:
            row_styles.append(("BACKGROUND", (0, i), (-1, i), LIGHT_BLUE))
    items_t.setStyle(TableStyle(row_styles))
    story.append(items_t)
    story.append(Spacer(1, 4 * mm))

    # 小計 / 稅 / 合計
    tax   = subtotal * data["tax_rate"]
    total = subtotal + tax

    totals_rows = [["Subtotal:", f"${subtotal:,.2f}"]]
    if data["tax_rate"] > 0:
        totals_rows.append([f"Tax ({data['tax_rate']*100:.0f}%):", f"${tax:,.2f}"])
    totals_rows.append(["TOTAL DUE:", f"${total:,.2f}"])

    tt = Table(totals_rows, colWidths=[130 * mm, 40 * mm])
    tt.setStyle(TableStyle([
        ("ALIGN",         (0, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, -1), (-1, -1), 11),
        ("BACKGROUND",    (0, -1), (-1, -1), DARK_BLUE),
        ("TEXTCOLOR",     (0, -1), (-1, -1), colors.white),
        ("LINEABOVE",     (0, -1), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(tt)
    story.append(Spacer(1, 6 * mm))

    # 備註 + 頁尾
    if data.get("notes"):
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(
            f"<b>Notes:</b> {data['notes']}",
            ParagraphStyle("notes", fontSize=8, textColor=colors.grey),
        ))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "Thank you for your business!",
        ParagraphStyle("footer", fontSize=9, alignment=TA_CENTER, textColor=MID_BLUE),
    ))

    doc.build(story)


def generate_sample_csv() -> None:
    """
    產生一張 CSV 格式的發票（模擬從 ERP 系統匯出）。
    → AI 應分類為 services（法律顧問費）
    """
    csv_path = OUTPUT_DIR / "INV-2024-006_legal_services.csv"
    rows = [
        ["invoice_number", "vendor_name", "invoice_date",
         "description", "quantity", "unit_price"],
        ["INV-2024-006", "Chen & Partners Law Firm", "2024-01-25",
         "Corporate Legal Consultation (5 hrs)", "5", "350.00"],
        ["INV-2024-006", "Chen & Partners Law Firm", "2024-01-25",
         "Contract Review & Drafting", "1", "800.00"],
        ["INV-2024-006", "Chen & Partners Law Firm", "2024-01-25",
         "Document Filing Fees", "1", "120.00"],
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    print(f"  ✓ CSV  → {csv_path.name}")


def generate_all_samples() -> None:
    """產生所有範例發票並印出摘要。"""
    print(f"\n產生範例發票至：{OUTPUT_DIR}\n")
    for inv in SAMPLE_INVOICES:
        out = OUTPUT_DIR / inv["filename"]
        _build_pdf(inv, out)
        flag = "  ⚠  DUPLICATE（異常偵測用）" if "DUPLICATE" in inv["filename"] else ""
        print(f"  ✓ PDF  → {inv['filename']}{flag}")
    generate_sample_csv()
    print(f"\n共 {len(SAMPLE_INVOICES)} 張 PDF + 1 張 CSV 已產生。\n")


if __name__ == "__main__":
    generate_all_samples()
