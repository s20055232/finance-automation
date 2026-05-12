"""
models.py — 系統資料模型

定義四個 Phase 之間傳遞的資料結構（dataclass）。
用 dataclass 而非 dict 的原因：型別提示、IDE 自動補全、更清晰的 API 合約。

資料流：
    InvoiceData  →  ClassifiedInvoice  →  ReconciliationReport  →  Excel / Email
    (Phase 1)        (Phase 2)              (Phase 3)              (Phase 4)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Phase 1 輸出：發票原始資料 ────────────────────────────────────────────────

@dataclass
class LineItem:
    """發票的一個明細行，例如「MacBook Pro x2 @ $1,999」。"""
    description: str
    quantity: float
    unit_price: float
    amount: float       # = quantity × unit_price


@dataclass
class InvoiceData:
    """
    從 PDF / CSV 擷取出來的發票資料。

    extraction_method: "pdf_text" | "csv" | "excel"
    extraction_confidence: "high" | "medium" | "low"
      high   = 所有必要欄位都找到了
      medium = 找到總金額但缺少部分明細
      low    = 只靠猜測解析，需要人工複核
    """
    invoice_number: str
    vendor_name: str
    invoice_date: str           # ISO 格式：YYYY-MM-DD
    due_date: Optional[str]
    line_items: list[LineItem]
    subtotal: float
    tax_amount: float
    total_amount: float
    currency: str               # 預設 "USD"
    source_file: str            # 原始檔名，供追蹤用
    extraction_method: str
    raw_text: Optional[str]     # PDF 原始文字，供 AI 分類參考
    extraction_confidence: str  # "high" | "medium" | "low"


# ── Phase 2 輸出：AI 分類 + 借貸分錄 ─────────────────────────────────────────

@dataclass
class JournalEntry:
    """
    一筆借貸分錄。

    會計規則：
      每張發票產生「成對」的分錄，借方總計 = 貸方總計 = 發票金額。

    範例（買電腦 $4,000）：
      JournalEntry("Equipment", "Asset", debit=4000, credit=0, ...)
      JournalEntry("Cash",      "Asset", debit=0,    credit=4000, ...)
    """
    account_name: str
    account_type: str       # "Asset" | "Liability" | "Expense" | "Revenue" | "Equity"
    debit_amount: float     # 借方金額，若為貸方則為 0.0
    credit_amount: float    # 貸方金額，若為借方則為 0.0
    description: str        # 例如 "Equipment purchase: MacBook Pro from Acme Tech"


@dataclass
class ClassifiedInvoice:
    """
    Phase 2 的完整輸出：原始發票 + AI 分類結果 + 借貸分錄。

    classification_source: "ai" | "fallback_rules"
      ai            = Claude API 分類
      fallback_rules = 關鍵字規則（API 不可用時使用）

    storage_key: 存入 Object Storage 後的 key，例如 "invoices/2024/01/INV-001.pdf"
                 若尚未存入則為 None。
    """
    invoice: InvoiceData
    expense_category: str           # 對應 config.EXPENSE_CATEGORIES 其中之一
    expense_subcategory: str        # 更細的分類，例如 "computer_hardware"
    classification_confidence: str  # "high" | "medium" | "low"
    classification_source: str      # "ai" | "fallback_rules"
    journal_entries: list[JournalEntry]
    ai_reasoning: Optional[str]     # Claude 的說明，供稽核用
    storage_key: Optional[str] = None  # 存入 Object Storage 後填入


# ── Phase 3 輸出：對帳報告 ────────────────────────────────────────────────────

@dataclass
class AnomalyFlag:
    """
    異常旗標。

    severity:
      critical = 必須人工處理（借貸不平、重複發票）
      warning  = 應注意但不一定是錯誤（金額過大、低信心分類）
      info     = 僅供參考（缺少發票號碼、日期超過 90 天）
    """
    severity: str           # "critical" | "warning" | "info"
    anomaly_type: str       # "unbalanced" | "duplicate" | "large_amount" | 等
    invoice_number: str
    vendor_name: str
    description: str        # 人類可讀的說明
    amount: Optional[float]
    source_file: str = ""   # 對應 InvoiceData.source_file，唯一識別 invoice 實例


@dataclass
class ReconciliationReport:
    """
    Phase 3 的完整輸出：試算表 + 所有異常旗標 + 統計摘要。

    trial_balance: 每個帳戶的借貸合計，用 dict 表示，格式：
        {
          "Cash":      {"debit": 0.0,   "credit": 15450.0, "type": "Asset"},
          "Equipment": {"debit": 4097.0, "credit": 0.0,    "type": "Asset"},
          ...
        }
    is_balanced: 總借方 == 總貸方（誤差 < $0.01）
    """
    trial_balance: dict[str, dict]
    total_debits: float
    total_credits: float
    is_balanced: bool
    anomalies: list[AnomalyFlag]
    processed_invoices: list[ClassifiedInvoice]
    processing_date: str        # ISO 格式：YYYY-MM-DD
    summary_stats: dict         # 各費用類別統計、總金額等
