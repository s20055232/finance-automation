"""
journal.py — Phase 2b：從分類結果產生借貸分錄

=== 雙式記帳原則 ===
每張發票產生成對的借貸分錄，確保：
  總借方金額 == 總貸方金額 == 發票金額

一般發票（無稅金）：2 筆分錄
  借：費用科目（發票全額）
  貸：現金 / 應付帳款（發票全額）

含稅金發票：3 筆分錄
  借：費用科目（稅前小計）
  借：Tax Expense（稅金）
  貸：現金 / 應付帳款（含稅全額）

=== 帳戶選擇優先順序 ===
  高 / 中信心度（AI 分類）→ 使用 Claude 建議的帳戶
  低信心度 or 關鍵字規則   → 使用 config.CATEGORY_ACCOUNTS 預設值
"""

import logging
from src.models import InvoiceData, JournalEntry
from config import CATEGORY_ACCOUNTS, ACCOUNT_TYPES

logger = logging.getLogger(__name__)


def generate_journal_entries(
    invoice: InvoiceData,
    classification: dict,
) -> list[JournalEntry]:
    """
    產生這張發票的所有借貸分錄。

    classification 來自 classifier.classify_invoice()，必須包含：
      expense_category, classification_confidence, classification_source,
      suggested_debit_account, suggested_credit_account
    """
    category = classification.get("expense_category", "other")
    confidence = classification.get("classification_confidence", "low")
    source = classification.get("classification_source", "fallback_rules")

    use_ai_accounts = confidence in ("high", "medium") and source == "ai"

    if use_ai_accounts:
        debit_account = classification["suggested_debit_account"]
        credit_account = classification["suggested_credit_account"]
    else:
        fallback = CATEGORY_ACCOUNTS.get(category, CATEGORY_ACCOUNTS["other"])
        debit_account = fallback["debit"]
        credit_account = fallback["credit"]

    debit_type = ACCOUNT_TYPES.get(debit_account, "Expense")
    credit_type = ACCOUNT_TYPES.get(credit_account, "Asset")

    desc = f"{category.capitalize()} expense: {invoice.vendor_name} ({invoice.invoice_number})"

    entries: list[JournalEntry] = []

    if invoice.tax_amount > 0.001:
        # 3 筆：費用（稅前）+ 稅金 + 貸方（全額）
        entries.append(JournalEntry(
            account_name=debit_account,
            account_type=debit_type,
            debit_amount=round(invoice.subtotal, 2),
            credit_amount=0.0,
            description=desc,
        ))
        entries.append(JournalEntry(
            account_name="Tax Expense",
            account_type="Expense",
            debit_amount=round(invoice.tax_amount, 2),
            credit_amount=0.0,
            description=f"Tax on {invoice.invoice_number}",
        ))
        entries.append(JournalEntry(
            account_name=credit_account,
            account_type=credit_type,
            debit_amount=0.0,
            credit_amount=round(invoice.total_amount, 2),
            description=desc,
        ))
    else:
        # 2 筆：費用（全額）+ 貸方（全額）
        entries.append(JournalEntry(
            account_name=debit_account,
            account_type=debit_type,
            debit_amount=round(invoice.total_amount, 2),
            credit_amount=0.0,
            description=desc,
        ))
        entries.append(JournalEntry(
            account_name=credit_account,
            account_type=credit_type,
            debit_amount=0.0,
            credit_amount=round(invoice.total_amount, 2),
            description=desc,
        ))

    if not validate_balance(entries):
        total_dr = sum(e.debit_amount for e in entries)
        total_cr = sum(e.credit_amount for e in entries)
        raise ValueError(
            f"Journal entries unbalanced for {invoice.invoice_number}: "
            f"debits={total_dr:.2f}, credits={total_cr:.2f}"
        )

    return entries


def validate_balance(entries: list[JournalEntry]) -> bool:
    """借貸平衡檢查：總借方 == 總貸方（誤差 < $0.01）。"""
    total_debits = sum(e.debit_amount for e in entries)
    total_credits = sum(e.credit_amount for e in entries)
    return abs(total_debits - total_credits) < 0.01
