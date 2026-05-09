"""
test_reconciler.py — Phase 3 Trial Balance + Anomaly Detection 測試

=== 測試範圍 ===
  build_trial_balance()   — Journal Entries → Account 彙總
  detect_anomalies()      — 所有 Anomaly 規則
  reconcile()             — 整合入口（Trial Balance + Anomalies → ReconciliationReport）

=== Fixture 說明 ===
  make_ci()   — 快速建立 ClassifiedInvoice 的工廠函式
                避免每個 test 都要手寫完整的 InvoiceData + JournalEntry

=== 會計業務規則 ===
  Trial Balance 的核心假設：所有 Journal Entries 的 Debit 總計 = Credit 總計。
  任何不平衡都代表資料有問題，必須在輸出 Excel 報表前發現並標記。
"""
import pytest
from datetime import date, timedelta
from src.reconciler import (
    reconcile, build_trial_balance, detect_anomalies,
    _detect_exact_duplicates, _detect_near_duplicates,
    _detect_large_amounts, _detect_future_dates,
    _detect_low_confidence, _detect_missing_invoice_number,
    _detect_old_invoices, _detect_unbalanced_entries,
)
from src.models import ClassifiedInvoice, InvoiceData, JournalEntry, LineItem


# ── Test Fixtures ─────────────────────────────────────────────────────────────

def make_invoice(
    invoice_number="INV-001",
    vendor_name="Acme Tech",
    total_amount=1000.0,
    invoice_date=None,
    tax_amount=0.0,
) -> InvoiceData:
    """快速建立 InvoiceData，只填測試需要的欄位，其餘使用合理預設值。"""
    if invoice_date is None:
        invoice_date = date.today().isoformat()
    subtotal = total_amount - tax_amount
    return InvoiceData(
        invoice_number=invoice_number,
        vendor_name=vendor_name,
        invoice_date=invoice_date,
        due_date=None,
        line_items=[LineItem("Item", 1, total_amount, subtotal)],
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount,
        currency="USD",
        source_file="test.pdf",
        extraction_method="pdf_text",
        raw_text=None,
        extraction_confidence="high",
    )


def make_ci(
    invoice_number="INV-001",
    vendor_name="Acme Tech",
    total_amount=1000.0,
    invoice_date=None,
    tax_amount=0.0,
    confidence="high",
    source="ai",
    category="equipment",
    debit_account="Equipment",
    credit_account="Cash",
    balanced=True,           # False 時故意讓 Debit ≠ Credit，觸發 unbalanced anomaly
) -> ClassifiedInvoice:
    """
    ClassifiedInvoice 工廠函式。

    balanced=True  → 產生正確的 2 筆 Journal Entries（Debit = Credit）
    balanced=False → 故意讓 Credit 少 $1，用於測試 unbalanced_entries 規則
    """
    invoice = make_invoice(invoice_number, vendor_name, total_amount, invoice_date, tax_amount)
    credit_amount = total_amount if balanced else total_amount - 1.0
    entries = [
        JournalEntry(debit_account,  "Expense", total_amount,   0.0,          f"Debit {invoice_number}"),
        JournalEntry(credit_account, "Asset",   0.0,            credit_amount, f"Credit {invoice_number}"),
    ]
    return ClassifiedInvoice(
        invoice=invoice,
        expense_category=category,
        expense_subcategory="general",
        classification_confidence=confidence,
        classification_source=source,
        journal_entries=entries,
        ai_reasoning="test",
    )


# ── Trial Balance Tests ───────────────────────────────────────────────────────

class TestBuildTrialBalance:
    def test_aggregates_by_account(self):
        # 兩張 Invoice 都用 Equipment / Cash → 兩筆加總在同一個 Account 下
        invoices = [make_ci(total_amount=1000.0), make_ci(total_amount=500.0)]
        tb = build_trial_balance(invoices)
        assert tb["Equipment"]["debit"] == 1500.0
        assert tb["Cash"]["credit"] == 1500.0

    def test_multiple_accounts(self):
        # 不同 Account 的 Journal Entries 應分開彙總，不互相影響
        invoices = [
            make_ci(total_amount=1000.0, debit_account="Equipment", credit_account="Cash"),
            make_ci(total_amount=500.0,  debit_account="Rent Expense", credit_account="Cash"),
        ]
        tb = build_trial_balance(invoices)
        assert "Equipment"    in tb
        assert "Rent Expense" in tb
        assert tb["Cash"]["credit"] == 1500.0   # Cash 是兩張 Invoice 共用的 Credit Account

    def test_preserves_account_type(self):
        # Account Type 用於 Trial Balance 報表的分類（Asset / Liability / Expense 等）
        invoices = [make_ci(debit_account="Equipment", credit_account="Cash")]
        tb = build_trial_balance(invoices)
        assert tb["Equipment"]["type"] == "Expense"   # make_ci 預設 Debit type = "Expense"
        assert tb["Cash"]["type"] == "Asset"           # make_ci 預設 Credit type = "Asset"

    def test_empty_invoices(self):
        assert build_trial_balance([]) == {}


# ── Anomaly Detection Tests ───────────────────────────────────────────────────

class TestDetectExactDuplicates:
    def test_flags_same_vendor_and_number(self):
        # 同一 Invoice Number + 同一 Vendor → CRITICAL duplicate
        invoices = [
            make_ci("INV-001", "Acme Tech"),
            make_ci("INV-001", "Acme Tech"),   # 完全重複
        ]
        flags = _detect_exact_duplicates(invoices)
        assert len(flags) == 1
        assert flags[0].severity == "critical"
        assert flags[0].anomaly_type == "duplicate_invoice"

    def test_different_vendor_not_flagged(self):
        # 同一 Invoice Number 但不同 Vendor → 不是 duplicate（不同廠商可以有相同編號）
        invoices = [
            make_ci("INV-001", "Acme Tech"),
            make_ci("INV-001", "Beta Corp"),
        ]
        assert _detect_exact_duplicates(invoices) == []

    def test_case_insensitive_vendor_match(self):
        # Vendor 名稱大小寫不影響比對：ACME TECH = Acme Tech = acme tech
        invoices = [
            make_ci("INV-001", "ACME TECH"),
            make_ci("INV-001", "acme tech"),
        ]
        flags = _detect_exact_duplicates(invoices)
        assert len(flags) == 1


class TestDetectNearDuplicates:
    def test_flags_same_vendor_similar_amount_within_window(self):
        # 同 Vendor、金額差 $0.50（< $1）、日期差 5 天（< 30 天）→ WARNING near-duplicate
        today = date.today().isoformat()
        five_days_ago = (date.today() - timedelta(days=5)).isoformat()
        invoices = [
            make_ci("INV-001", "Acme Tech", total_amount=1000.00, invoice_date=today),
            make_ci("INV-002", "Acme Tech", total_amount=1000.50, invoice_date=five_days_ago),
        ]
        flags = _detect_near_duplicates(invoices)
        assert len(flags) == 1
        assert flags[0].severity == "warning"
        assert flags[0].anomaly_type == "near_duplicate"

    def test_amount_diff_over_threshold_not_flagged(self):
        # 金額差 $5（> $1）→ 不視為 near-duplicate
        today = date.today().isoformat()
        invoices = [
            make_ci("INV-001", "Acme Tech", total_amount=1000.0, invoice_date=today),
            make_ci("INV-002", "Acme Tech", total_amount=1005.0, invoice_date=today),
        ]
        assert _detect_near_duplicates(invoices) == []

    def test_outside_date_window_not_flagged(self):
        # 日期差 60 天（> 30 天的 DUPLICATE_WINDOW_DAYS）→ 不視為 near-duplicate
        today = date.today().isoformat()
        sixty_days_ago = (date.today() - timedelta(days=60)).isoformat()
        invoices = [
            make_ci("INV-001", "Acme Tech", total_amount=1000.0, invoice_date=today),
            make_ci("INV-002", "Acme Tech", total_amount=1000.5, invoice_date=sixty_days_ago),
        ]
        assert _detect_near_duplicates(invoices) == []

    def test_different_vendors_not_flagged(self):
        today = date.today().isoformat()
        invoices = [
            make_ci("INV-001", "Acme Tech", total_amount=1000.0, invoice_date=today),
            make_ci("INV-002", "Beta Corp", total_amount=1000.0, invoice_date=today),
        ]
        assert _detect_near_duplicates(invoices) == []


class TestDetectLargeAmounts:
    def test_flags_above_threshold(self):
        # 超過 $10,000（LARGE_AMOUNT_THRESHOLD）→ WARNING
        invoices = [make_ci(total_amount=15000.0)]
        flags = _detect_large_amounts(invoices)
        assert len(flags) == 1
        assert flags[0].severity == "warning"
        assert flags[0].anomaly_type == "large_amount"

    def test_exactly_at_threshold_not_flagged(self):
        # 恰好等於 threshold → 不標記（只有「超過」才標記）
        invoices = [make_ci(total_amount=10000.0)]
        assert _detect_large_amounts(invoices) == []

    def test_below_threshold_not_flagged(self):
        invoices = [make_ci(total_amount=500.0)]
        assert _detect_large_amounts(invoices) == []


class TestDetectFutureDates:
    def test_flags_future_invoice(self):
        # Invoice Date 在明天 → WARNING（不應該收到未來的發票）
        future = (date.today() + timedelta(days=1)).isoformat()
        invoices = [make_ci(invoice_date=future)]
        flags = _detect_future_dates(invoices)
        assert len(flags) == 1
        assert flags[0].severity == "warning"
        assert flags[0].anomaly_type == "future_date"

    def test_today_not_flagged(self):
        # 今天開立的 Invoice → 正常
        invoices = [make_ci(invoice_date=date.today().isoformat())]
        assert _detect_future_dates(invoices) == []

    def test_past_date_not_flagged(self):
        invoices = [make_ci(invoice_date="2024-01-01")]
        assert _detect_future_dates(invoices) == []


class TestDetectLowConfidence:
    def test_flags_low_ai_confidence(self):
        # AI 分類信心度 low → WARNING，Account 分配可能錯誤
        invoices = [make_ci(confidence="low", source="ai")]
        flags = _detect_low_confidence(invoices)
        assert len(flags) == 1
        assert flags[0].anomaly_type == "low_confidence"

    def test_flags_fallback_rules_source(self):
        # 即使 confidence 是 high，只要 source 是 fallback_rules 就標記
        # 因為帳戶建議也是來自規則而非 AI，準確度較低
        invoices = [make_ci(confidence="high", source="fallback_rules")]
        flags = _detect_low_confidence(invoices)
        assert len(flags) == 1

    def test_high_confidence_ai_not_flagged(self):
        invoices = [make_ci(confidence="high", source="ai")]
        assert _detect_low_confidence(invoices) == []

    def test_medium_confidence_ai_not_flagged(self):
        invoices = [make_ci(confidence="medium", source="ai")]
        assert _detect_low_confidence(invoices) == []


class TestDetectMissingInvoiceNumber:
    @pytest.mark.parametrize("number", ["", "unknown", "N/A", "none", "-", "—"])
    def test_flags_missing_numbers(self, number):
        # 常見的「無效」Invoice Number 都應被標記
        invoices = [make_ci(invoice_number=number)]
        flags = _detect_missing_invoice_number(invoices)
        assert len(flags) == 1
        assert flags[0].anomaly_type == "missing_invoice_number"

    def test_valid_number_not_flagged(self):
        invoices = [make_ci(invoice_number="INV-2024-001")]
        assert _detect_missing_invoice_number(invoices) == []


class TestDetectOldInvoices:
    def test_flags_invoice_over_90_days(self):
        # 91 天前的 Invoice → INFO（超過常見的 90 天報帳期限）
        old_date = (date.today() - timedelta(days=91)).isoformat()
        invoices = [make_ci(invoice_date=old_date)]
        flags = _detect_old_invoices(invoices)
        assert len(flags) == 1
        assert flags[0].severity == "info"
        assert flags[0].anomaly_type == "old_invoice"

    def test_invoice_within_90_days_not_flagged(self):
        recent = (date.today() - timedelta(days=89)).isoformat()
        invoices = [make_ci(invoice_date=recent)]
        assert _detect_old_invoices(invoices) == []


class TestDetectUnbalancedEntries:
    def test_flags_unbalanced_journal_entry(self):
        # Journal Entries 的 Debit ≠ Credit → CRITICAL（雙式記帳最基本的規則）
        invoices = [make_ci(balanced=False)]
        flags = _detect_unbalanced_entries(invoices)
        assert len(flags) == 1
        assert flags[0].severity == "critical"
        assert flags[0].anomaly_type == "unbalanced_entries"

    def test_balanced_entries_not_flagged(self):
        invoices = [make_ci(balanced=True)]
        assert _detect_unbalanced_entries(invoices) == []


# ── Reconcile Integration Tests ───────────────────────────────────────────────

class TestReconcile:
    def test_returns_reconciliation_report(self):
        invoices = [make_ci("INV-001", total_amount=1000.0)]
        report = reconcile(invoices)
        assert report.total_debits == 1000.0
        assert report.total_credits == 1000.0
        assert report.is_balanced is True

    def test_anomalies_sorted_by_severity(self):
        # 結果應依 CRITICAL → WARNING → INFO 排序，讓使用者看到最嚴重的問題在最上面
        today = date.today().isoformat()
        invoices = [
            make_ci("INV-001", "Acme", total_amount=15000.0, invoice_date=today),  # WARNING: large amount
            make_ci("INV-001", "Acme", total_amount=15000.0, invoice_date=today),  # CRITICAL: duplicate
            make_ci("INV-002", confidence="low", source="fallback_rules"),          # WARNING: low confidence
        ]
        report = reconcile(invoices)
        severities = [f.severity for f in report.anomalies]
        critical_indices = [i for i, s in enumerate(severities) if s == "critical"]
        warning_indices  = [i for i, s in enumerate(severities) if s == "warning"]
        if critical_indices and warning_indices:
            assert max(critical_indices) < min(warning_indices)

    def test_summary_stats_counts_correctly(self):
        invoices = [
            make_ci("INV-001", total_amount=1000.0, category="equipment"),
            make_ci("INV-002", total_amount=500.0,  category="equipment"),
            make_ci("INV-003", total_amount=200.0,  category="software"),
        ]
        report = reconcile(invoices)
        assert report.summary_stats["invoice_count"] == 3
        assert report.summary_stats["total_amount"] == 1700.0
        assert report.summary_stats["by_category"]["equipment"]["count"] == 2
        assert report.summary_stats["by_category"]["software"]["count"] == 1

    def test_processing_date_is_today(self):
        report = reconcile([make_ci()])
        assert report.processing_date == date.today().isoformat()
