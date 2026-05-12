"""
reconciler.py — Phase 3：Trial Balance + Anomaly Detection

=== Trial Balance ===
把所有發票的 Journal Entries，按 Account 彙總：

  Account               Debit       Credit     Net
  Equipment           4,097.98        0.00   4,097.98
  Cash                    0.00   14,062.48 -14,062.48
  ...
  ─────────────────────────────────────────────────────
  Total              14,062.48   14,062.48       0.00  ← 必須平衡

=== Anomaly 分級 ===
  CRITICAL  必須人工處理，否則財報就是錯的
            • Debit / Credit 不平衡（單張或整批）
            • 完全重複 Invoice（同一 Invoice Number + 同一 Vendor）

  WARNING   應注意，但不一定是錯的
            • Near-duplicate（同 Vendor、金額差 $1 以內、30 天內）
            • 金額超過 Large Amount Threshold（預設 $10,000）
            • Future-dated Invoice（Invoice Date 在今天之後）
            • 低信心分類（AI 或關鍵字規則沒把握）

  INFO      僅供參考
            • 缺少 Invoice Number
            • Invoice Date 超過 90 天
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from src.models import AnomalyFlag, ClassifiedInvoice, ReconciliationReport
from config import LARGE_AMOUNT_THRESHOLD, DUPLICATE_WINDOW_DAYS

logger = logging.getLogger(__name__)


# ── 主入口 ────────────────────────────────────────────────────────────────────

def reconcile(classified_invoices: list[ClassifiedInvoice]) -> ReconciliationReport:
    """
    對一批已分類 Invoices 進行完整 Reconciliation。
    回傳 ReconciliationReport，供 reporter.py 產生 Excel 報表。
    """
    trial_balance = build_trial_balance(classified_invoices)

    total_debits  = sum(v["debit"]  for v in trial_balance.values())
    total_credits = sum(v["credit"] for v in trial_balance.values())
    is_balanced   = abs(total_debits - total_credits) < 0.01

    anomalies = detect_anomalies(classified_invoices, trial_balance, is_balanced)

    logger.info(
        "Reconciliation complete: %d invoices, debits=%.2f, credits=%.2f, "
        "balanced=%s, anomalies=%d",
        len(classified_invoices), total_debits, total_credits,
        is_balanced, len(anomalies),
    )

    return ReconciliationReport(
        trial_balance=trial_balance,
        total_debits=total_debits,
        total_credits=total_credits,
        is_balanced=is_balanced,
        anomalies=anomalies,
        processed_invoices=classified_invoices,
        processing_date=date.today().isoformat(),
        summary_stats=_build_summary_stats(classified_invoices, anomalies),
    )


# ── Trial Balance ─────────────────────────────────────────────────────────────

def build_trial_balance(
    classified_invoices: list[ClassifiedInvoice],
) -> dict[str, dict]:
    """
    彙總所有 Journal Entries，回傳以 Account Name 為 key 的 dict：
      { "Cash": {"debit": 0.0, "credit": 14062.48, "type": "Asset"}, ... }
    """
    balance: dict[str, dict] = defaultdict(lambda: {"debit": 0.0, "credit": 0.0, "type": "Expense"})

    for ci in classified_invoices:
        for entry in ci.journal_entries:
            acct = balance[entry.account_name]
            acct["debit"]  = round(acct["debit"]  + entry.debit_amount,  2)
            acct["credit"] = round(acct["credit"] + entry.credit_amount, 2)
            acct["type"]   = entry.account_type   # 同一 Account 的 type 一致

    return dict(balance)


# ── Anomaly Detection ─────────────────────────────────────────────────────────

def detect_anomalies(
    classified_invoices: list[ClassifiedInvoice],
    trial_balance: dict[str, dict],
    is_balanced: bool,
) -> list[AnomalyFlag]:
    """
    對整批 Invoices 跑所有 Anomaly 規則，回傳 AnomalyFlag 清單（嚴重程度由高到低排序）。
    """
    flags: list[AnomalyFlag] = []

    # ── CRITICAL ──────────────────────────────────────────────────────────────

    if not is_balanced:
        total_dr = sum(v["debit"]  for v in trial_balance.values())
        total_cr = sum(v["credit"] for v in trial_balance.values())
        flags.append(AnomalyFlag(
            severity="critical",
            anomaly_type="trial_balance_unbalanced",
            invoice_number="—",
            vendor_name="—",
            description=(
                f"Trial Balance is unbalanced: "
                f"total debits ${total_dr:,.2f} ≠ total credits ${total_cr:,.2f}. "
                "Review all Journal Entries."
            ),
            amount=abs(total_dr - total_cr),
        ))

    flags.extend(_detect_unbalanced_entries(classified_invoices))
    flags.extend(_detect_exact_duplicates(classified_invoices))

    # ── WARNING ───────────────────────────────────────────────────────────────

    flags.extend(_detect_near_duplicates(classified_invoices))
    flags.extend(_detect_large_amounts(classified_invoices))
    flags.extend(_detect_future_dates(classified_invoices))
    flags.extend(_detect_low_confidence(classified_invoices))

    # ── INFO ──────────────────────────────────────────────────────────────────

    flags.extend(_detect_missing_invoice_number(classified_invoices))
    flags.extend(_detect_old_invoices(classified_invoices))

    return sorted(flags, key=lambda f: {"critical": 0, "warning": 1, "info": 2}[f.severity])


# ── CRITICAL Rules ────────────────────────────────────────────────────────────

def _detect_unbalanced_entries(
    classified_invoices: list[ClassifiedInvoice],
) -> list[AnomalyFlag]:
    """
    單張 Invoice 的 Debit / Credit 不平衡。
    正常情況下 journal.py 已攔截，這裡是第二道防線。
    """
    flags = []
    for ci in classified_invoices:
        total_dr = sum(e.debit_amount  for e in ci.journal_entries)
        total_cr = sum(e.credit_amount for e in ci.journal_entries)
        if abs(total_dr - total_cr) >= 0.01:
            flags.append(AnomalyFlag(
                severity="critical",
                anomaly_type="unbalanced_entries",
                invoice_number=ci.invoice.invoice_number,
                vendor_name=ci.invoice.vendor_name,
                description=(
                    f"Journal Entries unbalanced: "
                    f"debits ${total_dr:,.2f} ≠ credits ${total_cr:,.2f}"
                ),
                amount=abs(total_dr - total_cr),
                source_file=ci.invoice.source_file,
            ))
    return flags


def _detect_exact_duplicates(
    classified_invoices: list[ClassifiedInvoice],
) -> list[AnomalyFlag]:
    """
    完全重複：同一 Vendor + 同一 Invoice Number 出現兩次以上。
    最常見原因：Vendor 重複開立、系統重複匯入。
    """
    seen: dict[tuple, ClassifiedInvoice] = {}
    flags = []

    for ci in classified_invoices:
        key = (ci.invoice.vendor_name.lower(), ci.invoice.invoice_number.upper())
        if key in seen:
            flags.append(AnomalyFlag(
                severity="critical",
                anomaly_type="duplicate_invoice",
                invoice_number=ci.invoice.invoice_number,
                vendor_name=ci.invoice.vendor_name,
                description=(
                    f"Duplicate Invoice: "
                    f"{ci.invoice.vendor_name} / {ci.invoice.invoice_number} "
                    f"appears more than once."
                ),
                amount=ci.invoice.total_amount,
                source_file=ci.invoice.source_file,
            ))
        else:
            seen[key] = ci

    return flags


# ── WARNING Rules ─────────────────────────────────────────────────────────────

def _detect_near_duplicates(
    classified_invoices: list[ClassifiedInvoice],
) -> list[AnomalyFlag]:
    """
    Near-duplicate：同一 Vendor 在 DUPLICATE_WINDOW_DAYS 天內有金額差異 $1 以內的 Invoices。
    可能是 Vendor 重複請款但故意微調金額，以規避完全重複檢查。
    """
    flags = []
    invoices = [ci.invoice for ci in classified_invoices]
    already_flagged: set[str] = set()

    for i, inv_a in enumerate(invoices):
        for inv_b in invoices[i + 1:]:
            if inv_a.vendor_name.lower() != inv_b.vendor_name.lower():
                continue
            if abs(inv_a.total_amount - inv_b.total_amount) > 1.0:
                continue
            try:
                date_a = datetime.fromisoformat(inv_a.invoice_date).date()
                date_b = datetime.fromisoformat(inv_b.invoice_date).date()
            except ValueError:
                continue
            if abs((date_a - date_b).days) <= DUPLICATE_WINDOW_DAYS:
                # 只對日期較晚的那張標記，避免兩張都被標記造成混淆
                later = inv_a if date_a >= date_b else inv_b
                if later.invoice_number in already_flagged:
                    continue
                already_flagged.add(later.invoice_number)
                flags.append(AnomalyFlag(
                    severity="warning",
                    anomaly_type="near_duplicate",
                    invoice_number=later.invoice_number,
                    vendor_name=later.vendor_name,
                    description=(
                        f"Near-duplicate: {later.vendor_name} has two Invoices "
                        f"within {DUPLICATE_WINDOW_DAYS} days "
                        f"with amounts ${inv_a.total_amount:,.2f} and ${inv_b.total_amount:,.2f}."
                    ),
                    amount=later.total_amount,
                    source_file=later.source_file,
                ))
    return flags


def _detect_large_amounts(
    classified_invoices: list[ClassifiedInvoice],
) -> list[AnomalyFlag]:
    """單張 Invoice 超過 Large Amount Threshold（預設 $10,000）→ 建議人工複核。"""
    flags = []
    for ci in classified_invoices:
        if ci.invoice.total_amount > LARGE_AMOUNT_THRESHOLD:
            flags.append(AnomalyFlag(
                severity="warning",
                anomaly_type="large_amount",
                invoice_number=ci.invoice.invoice_number,
                vendor_name=ci.invoice.vendor_name,
                description=(
                    f"Large amount ${ci.invoice.total_amount:,.2f} exceeds "
                    f"threshold ${LARGE_AMOUNT_THRESHOLD:,.2f}. Manual review recommended."
                ),
                amount=ci.invoice.total_amount,
                source_file=ci.invoice.source_file,
            ))
    return flags


def _detect_future_dates(
    classified_invoices: list[ClassifiedInvoice],
) -> list[AnomalyFlag]:
    """Invoice Date 在今天之後 → 可能是日期打錯或預開 Invoice。"""
    today = date.today()
    flags = []
    for ci in classified_invoices:
        try:
            inv_date = datetime.fromisoformat(ci.invoice.invoice_date).date()
        except ValueError:
            continue
        if inv_date > today:
            flags.append(AnomalyFlag(
                severity="warning",
                anomaly_type="future_date",
                invoice_number=ci.invoice.invoice_number,
                vendor_name=ci.invoice.vendor_name,
                description=(
                    f"Invoice Date {ci.invoice.invoice_date} is in the future. "
                    "Verify the date is correct."
                ),
                amount=ci.invoice.total_amount,
                source_file=ci.invoice.source_file,
            ))
    return flags


def _detect_low_confidence(
    classified_invoices: list[ClassifiedInvoice],
) -> list[AnomalyFlag]:
    """
    AI Classification Confidence 低 → Account 分配可能不準確，建議人工確認 Expense Category。
    注意：Fallback Rules（關鍵字規則）分類的 Invoices 一律視為低信心。
    """
    flags = []
    for ci in classified_invoices:
        if ci.classification_confidence == "low" or ci.classification_source == "fallback_rules":
            flags.append(AnomalyFlag(
                severity="warning",
                anomaly_type="low_confidence",
                invoice_number=ci.invoice.invoice_number,
                vendor_name=ci.invoice.vendor_name,
                description=(
                    f"Low confidence classification ({ci.classification_source}): "
                    f"category '{ci.expense_category}' may be incorrect. "
                    "Review and reclassify if needed."
                ),
                amount=ci.invoice.total_amount,
                source_file=ci.invoice.source_file,
            ))
    return flags


# ── INFO Rules ────────────────────────────────────────────────────────────────

def _detect_missing_invoice_number(
    classified_invoices: list[ClassifiedInvoice],
) -> list[AnomalyFlag]:
    """缺少 Invoice Number → 無法追蹤原始憑證，不符合一般稽核要求。"""
    missing = {"", "unknown", "n/a", "none", "-", "—"}
    flags = []
    for ci in classified_invoices:
        if ci.invoice.invoice_number.strip().lower() in missing:
            flags.append(AnomalyFlag(
                severity="info",
                anomaly_type="missing_invoice_number",
                invoice_number=ci.invoice.invoice_number,
                vendor_name=ci.invoice.vendor_name,
                description=(
                    f"{ci.invoice.vendor_name}: Invoice Number is missing or blank. "
                    "Request the Invoice Number from the Vendor."
                ),
                amount=ci.invoice.total_amount,
                source_file=ci.invoice.source_file,
            ))
    return flags


def _detect_old_invoices(
    classified_invoices: list[ClassifiedInvoice],
) -> list[AnomalyFlag]:
    """Invoice Date 超過 90 天 → 可能是遲交，確認是否已超過 Expense Period。"""
    cutoff = date.today() - timedelta(days=90)
    flags = []
    for ci in classified_invoices:
        try:
            inv_date = datetime.fromisoformat(ci.invoice.invoice_date).date()
        except ValueError:
            continue
        if inv_date < cutoff:
            age_days = (date.today() - inv_date).days
            flags.append(AnomalyFlag(
                severity="info",
                anomaly_type="old_invoice",
                invoice_number=ci.invoice.invoice_number,
                vendor_name=ci.invoice.vendor_name,
                description=(
                    f"Invoice is {age_days} days old (date: {ci.invoice.invoice_date}). "
                    "Confirm this is not a late submission past the Expense Period."
                ),
                amount=ci.invoice.total_amount,
                source_file=ci.invoice.source_file,
            ))
    return flags


# ── Summary Stats ─────────────────────────────────────────────────────────────

def _build_summary_stats(
    classified_invoices: list[ClassifiedInvoice],
    anomalies: list[AnomalyFlag],
) -> dict:
    by_category: dict[str, dict] = defaultdict(lambda: {"count": 0, "total": 0.0})
    by_source: dict[str, int]    = defaultdict(int)

    for ci in classified_invoices:
        cat = by_category[ci.expense_category]
        cat["count"] += 1
        cat["total"]  = round(cat["total"] + ci.invoice.total_amount, 2)
        by_source[ci.classification_source] += 1

    severity_counts: dict[str, int] = defaultdict(int)
    for flag in anomalies:
        severity_counts[flag.severity] += 1

    return {
        "invoice_count": len(classified_invoices),
        "total_amount":  round(sum(ci.invoice.total_amount for ci in classified_invoices), 2),
        "by_category":   dict(by_category),
        "by_source":     dict(by_source),
        "anomaly_counts": dict(severity_counts),
    }
