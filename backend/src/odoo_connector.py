"""
odoo_connector.py — Odoo 18 XML-RPC 整合

=== 資料流 ===
  讀取：Odoo vendor bills (account.move) → InvoiceData
  寫回：JournalEntry list → Odoo journal entry (account.move, type='entry')

=== 認證設定（.env）===
  ODOO_URL      = http://localhost:8069
  ODOO_DB       = odoo
  ODOO_USER     = admin
  ODOO_API_KEY  = <Odoo Settings → Users → API Keys 產生>

=== Graceful degradation ===
  ODOO_API_KEY 未設定時，fetch_vendor_bills() 直接回傳 []，
  系統仍可用 PDF/CSV pipeline 正常運作。
  fly.io 部署時只需設定此 env var 即可啟用 Odoo 整合。
"""

import os
import logging
import xmlrpc.client
from datetime import date
from functools import lru_cache
from dotenv import load_dotenv

from src.models import InvoiceData, JournalEntry, LineItem

load_dotenv()
logger = logging.getLogger(__name__)

ODOO_URL     = os.getenv("ODOO_URL",     "http://localhost:8069")
ODOO_DB      = os.getenv("ODOO_DB",      "odoo")
ODOO_USER    = os.getenv("ODOO_USER",    "admin")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")


# ── 連線 ─────────────────────────────────────────────────────────────────────

class OdooClient:
    """XML-RPC session。建立一次，重複使用。"""

    def __init__(
        self,
        url: str = ODOO_URL,
        db: str = ODOO_DB,
        user: str = ODOO_USER,
        api_key: str = ODOO_API_KEY,
    ) -> None:
        self.url = url
        self.db = db
        self.api_key = api_key

        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        self.uid: int = common.authenticate(db, user, api_key, {})
        if not self.uid:
            raise PermissionError(
                f"Odoo authentication failed for user '{user}' at {url}. "
                "Check ODOO_USER and ODOO_API_KEY in .env"
            )

        self._models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
        logger.info("Connected to Odoo at %s (uid=%d)", url, self.uid)

    def execute(self, model: str, method: str, *args, **kwargs) -> object:
        return self._models.execute_kw(
            self.db, self.uid, self.api_key,
            model, method, list(args), kwargs,
        )


def get_client() -> OdooClient | None:
    """
    回傳 OdooClient，若未設定 ODOO_API_KEY 則回傳 None（graceful degradation）。
    """
    if not ODOO_API_KEY:
        logger.info("ODOO_API_KEY not set — Odoo integration disabled")
        return None
    try:
        return OdooClient()
    except Exception as e:
        logger.warning("Cannot connect to Odoo: %s", e)
        return None


# ── 讀取：Vendor Bills → InvoiceData ─────────────────────────────────────────

def fetch_vendor_bills(client: OdooClient, *, limit: int = 100) -> list[InvoiceData]:
    """
    從 Odoo 拉取已確認（posted）的廠商發票，轉換成 InvoiceData。
    呼叫前請先用 get_client() 確認連線。
    """
    bills = client.execute(
        "account.move", "search_read",
        [["move_type", "=", "in_invoice"], ["state", "=", "posted"]],
        fields=[
            "name", "ref", "partner_id", "invoice_date", "invoice_date_due",
            "amount_untaxed", "amount_tax", "amount_total",
            "currency_id", "invoice_line_ids",
        ],
        limit=limit,
        order="invoice_date desc",
    )

    invoices: list[InvoiceData] = []
    for bill in bills:
        try:
            invoices.append(_bill_to_invoice(client, bill))
        except Exception as e:
            logger.warning("Skipping Odoo bill %s: %s", bill.get("name", "?"), e)

    logger.info("Fetched %d vendor bills from Odoo", len(invoices))
    return invoices


def _bill_to_invoice(client: OdooClient, bill: dict) -> InvoiceData:
    line_ids: list[int] = bill.get("invoice_line_ids", [])
    line_items = _fetch_line_items(client, line_ids) if line_ids else []

    vendor_name = bill["partner_id"][1] if bill.get("partner_id") else "Unknown Vendor"
    currency    = bill["currency_id"][1] if bill.get("currency_id") else "USD"
    invoice_date = str(bill.get("invoice_date") or date.today())
    due_date     = str(bill["invoice_date_due"]) if bill.get("invoice_date_due") else None

    return InvoiceData(
        # ref = vendor's own invoice number (set in seed_odoo.py / Odoo UI)
        # name = Odoo's auto-generated sequence (BILL/YYYY/XXXX)
        # Prefer ref so our duplicate detection works on the vendor's numbering.
        invoice_number=bill.get("ref") or bill.get("name", f"odoo:{bill['id']}"),
        vendor_name=vendor_name,
        invoice_date=invoice_date,
        due_date=due_date,
        line_items=line_items,
        subtotal=float(bill.get("amount_untaxed", 0)),
        tax_amount=float(bill.get("amount_tax", 0)),
        total_amount=float(bill.get("amount_total", 0)),
        currency=currency,
        source_file=f"odoo:{bill['id']}",
        extraction_method="odoo_xmlrpc",
        raw_text=None,
        extraction_confidence="high",
    )


def _fetch_line_items(client: OdooClient, line_ids: list[int]) -> list[LineItem]:
    if not line_ids:
        return []

    lines = client.execute(
        "account.move.line", "read",
        line_ids,
        fields=["name", "quantity", "price_unit", "price_subtotal", "display_type"],
    )

    # display_type is False/None for product lines; 'line_section'/'line_note' for headers/notes
    return [
        LineItem(
            description=ln.get("name") or "—",
            quantity=float(ln.get("quantity", 1)),
            unit_price=float(ln.get("price_unit", 0)),
            amount=float(ln.get("price_subtotal", 0)),
        )
        for ln in lines
        if not ln.get("display_type")
    ]


# ── 寫回：JournalEntry → Odoo journal entry ───────────────────────────────────

def write_journal_entries(
    client: OdooClient,
    invoice: InvoiceData,
    entries: list[JournalEntry],
    journal_name: str = "Miscellaneous Operations",
) -> int:
    """
    將 JournalEntry list 寫回 Odoo，建立並 post 一筆 journal entry。
    回傳建立的 account.move ID。

    帳戶名稱（如 "Equipment"、"Cash"）會自動對應到 Odoo chart of accounts。
    找不到的帳戶會被略過並記錄 warning。
    """
    journal_id = _find_journal(client, journal_name)
    move_lines = []

    for entry in entries:
        account_id = _find_account(client, entry.account_name)
        if account_id is None:
            logger.warning("Account '%s' not found in Odoo chart of accounts", entry.account_name)
            continue
        move_lines.append((0, 0, {
            "account_id": account_id,
            "name": entry.description,
            "debit": entry.debit_amount,
            "credit": entry.credit_amount,
        }))

    if not move_lines:
        raise ValueError(
            f"No matching Odoo accounts found for invoice {invoice.invoice_number}. "
            "Add accounts in Odoo → Accounting → Configuration → Chart of Accounts."
        )

    move_id: int = client.execute(
        "account.move", "create",
        {
            "move_type": "entry",
            "journal_id": journal_id,
            "date": invoice.invoice_date,
            "ref": f"AI: {invoice.invoice_number} ({invoice.vendor_name})",
            "line_ids": move_lines,
        },
    )

    client.execute("account.move", "action_post", [move_id])
    logger.info("Posted journal entry id=%d for %s", move_id, invoice.invoice_number)
    return move_id


# ── 帳戶 / 日記帳查詢（帶 cache）────────────────────────────────────────────
# lru_cache 以 client + name 為 key，同一 session 不重複查詢。

@lru_cache(maxsize=256)
def _find_account(client: OdooClient, name: str) -> int | None:
    results = client.execute(
        "account.account", "search_read",
        [["name", "ilike", name]],
        fields=["id", "name"],
        limit=1,
    )
    return results[0]["id"] if results else None


@lru_cache(maxsize=32)
def _find_journal(client: OdooClient, name: str) -> int:
    results = client.execute(
        "account.journal", "search_read",
        [["name", "ilike", name]],
        fields=["id", "name"],
        limit=1,
    )
    if not results:
        raise ValueError(
            f"Odoo journal '{name}' not found. "
            "Check Odoo → Accounting → Configuration → Journals."
        )
    return results[0]["id"]
