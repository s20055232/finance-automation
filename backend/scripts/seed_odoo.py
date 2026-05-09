"""
seed_odoo.py — 植入 6 張示範 Vendor Bills 到 Odoo

=== 示範資料 ===
  1. Acme Tech              — MacBook Pro ×2 + Hub     ($4,097.98) → equipment
  2. Downtown Office Spaces — 辦公室租金 January       ($3,500.00) → rent
  3. Digital Marketing Agency — Google Ads + SEO       ($3,000.00) → marketing
  4. City Power & Light     — 電費 + 滯納金            ($499.50)   → utilities
  5. CloudStack Inc.        — AWS + Slack               ($3,965.00) → software
  6. Acme Tech              — MacBook Pro ×1（故意重複）($1,999.00) → anomaly demo
     ↑ 與 #1 同 vendor + 同 ref（INV-2024-001），reconciler 應標記 CRITICAL duplicate

=== 前置條件 ===
  make odoo               → 等 Odoo 完全啟動（看到 HTTP service running）
  backend/.env            → ODOO_API_KEY=<從 Odoo Settings > Users > API Keys 取得>
  Odoo account 模組       → docker-compose 已設定 -i base,account，初始化後自動安裝

=== 執行 ===
  make seed-odoo
"""
import logging
import sys
from pathlib import Path

# Allow imports from backend/ root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.odoo_connector import OdooClient, get_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 示範發票資料 ──────────────────────────────────────────────────────────────

DEMO_BILLS = [
    {
        "vendor":         "Acme Tech",
        "ref":            "INV-2024-001",       # 廠商的發票號碼（存到 ref 欄位）
        "invoice_date":   "2024-01-15",
        "due_date":       "2024-02-15",
        "lines": [
            {"name": "MacBook Pro 14-inch",  "qty": 2, "price": 1999.00},
            {"name": "USB-C Hub Pro",        "qty": 1, "price":   99.98},
        ],
    },
    {
        "vendor":         "Downtown Office Spaces",
        "ref":            "RENT-2024-01",
        "invoice_date":   "2024-01-01",
        "due_date":       "2024-01-31",
        "lines": [
            {"name": "Office Rent — January 2024", "qty": 1, "price": 3500.00},
        ],
    },
    {
        "vendor":         "Digital Marketing Agency",
        "ref":            "DMA-2024-003",
        "invoice_date":   "2024-01-20",
        "due_date":       "2024-02-20",
        "lines": [
            {"name": "Google Ads Campaign",   "qty": 1, "price": 1500.00},
            {"name": "SEO Optimization",      "qty": 1, "price": 1000.00},
            {"name": "Social Media Content",  "qty": 1, "price":  500.00},
        ],
    },
    {
        "vendor":         "City Power & Light",
        "ref":            "CPL-JAN-2024",
        "invoice_date":   "2024-01-10",
        "due_date":       "2024-02-10",
        "lines": [
            {"name": "Electricity — January 2024",  "qty": 1, "price": 450.00},
            {"name": "Late Payment Fee",             "qty": 1, "price":  49.50},
        ],
    },
    {
        "vendor":         "CloudStack Inc.",
        "ref":            "CS-2024-0056",
        "invoice_date":   "2024-01-05",
        "due_date":       "2024-02-05",
        "lines": [
            {"name": "AWS Services — January",     "qty":  1, "price": 2965.00},
            {"name": "Slack Business (20 users)",  "qty": 20, "price":   50.00},
        ],
    },
    {
        # 故意重複：同 vendor（Acme Tech）+ 同 ref（INV-2024-001）
        # reconciler.detect_anomalies() 應標記 CRITICAL duplicate_invoice
        "vendor":         "Acme Tech",
        "ref":            "INV-2024-001",
        "invoice_date":   "2024-01-16",
        "due_date":       "2024-02-16",
        "lines": [
            {"name": "MacBook Pro 14-inch", "qty": 1, "price": 1999.00},
        ],
    },
]


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Connecting to Odoo...")
    client = get_client()
    if client is None:
        logger.error(
            "Cannot connect to Odoo.\n"
            "  1. Check that Odoo is running: make odoo\n"
            "  2. Check ODOO_API_KEY is set in backend/.env"
        )
        sys.exit(1)

    logger.info("Checking account module...")
    if not _check_account_module(client):
        logger.error(
            "Odoo 'account' module is not installed.\n"
            "  Restart Odoo to let -i base,account run: docker compose restart odoo\n"
            "  Then wait 5-8 minutes for the module to install."
        )
        sys.exit(1)

    expense_account_id = _find_expense_account(client)
    logger.info("Using expense account ID: %d", expense_account_id)

    created, skipped = 0, 0
    for bill in DEMO_BILLS:
        total = sum(l["qty"] * l["price"] for l in bill["lines"])
        try:
            bill_id = _create_vendor_bill(client, bill, expense_account_id)
            logger.info(
                "  ✓ [%s] %s / %s  $%.2f  → Odoo ID %d",
                bill["ref"], bill["vendor"], bill["invoice_date"], total, bill_id,
            )
            created += 1
        except Exception as exc:
            logger.warning("  ✗ [%s] %s — %s", bill["ref"], bill["vendor"], exc)
            skipped += 1

    logger.info("Done: %d created, %d skipped", created, skipped)
    if skipped:
        logger.info("Re-run the script to retry failed bills.")


# ── Odoo 操作 ─────────────────────────────────────────────────────────────────

def _check_account_module(client: OdooClient) -> bool:
    """Verify that the account module is installed by checking account.account."""
    try:
        client.execute("account.account", "search_count", [])
        return True
    except Exception:
        return False


def _find_expense_account(client: OdooClient) -> int:
    """
    Return the ID of an expense account to use for vendor bill lines.
    Tries generic 'expense' type first; falls back to creating one if needed.
    """
    accounts = client.execute(
        "account.account", "search_read",
        [["account_type", "=", "expense"]],
        fields=["id", "name", "code"],
        limit=1,
    )
    if accounts:
        logger.info("Found expense account: %s (%s)", accounts[0]["name"], accounts[0]["code"])
        return accounts[0]["id"]

    # Fallback: create a generic expense account
    # This is needed when no chart of accounts is configured.
    logger.warning("No expense account found — creating a generic one")
    account_id = client.execute("account.account", "create", {
        "name":         "General Expenses",
        "code":         "600000",
        "account_type": "expense",
    })
    return account_id


def _find_or_create_vendor(client: OdooClient, name: str) -> int:
    """Find a vendor partner by exact name, or create it."""
    partners = client.execute(
        "res.partner", "search_read",
        [["name", "=", name]],
        fields=["id", "name"],
        limit=1,
    )
    if partners:
        return partners[0]["id"]

    partner_id = client.execute("res.partner", "create", {
        "name":          name,
        "supplier_rank": 1,      # marks as a vendor in Odoo
        "company_type":  "company",
    })
    logger.info("  Created vendor: %s (ID %d)", name, partner_id)
    return partner_id


def _create_vendor_bill(
    client: OdooClient,
    bill: dict,
    expense_account_id: int,
) -> int:
    """
    Create and post a vendor bill (account.move, move_type='in_invoice').

    ref field stores the vendor's original invoice number so that
    odoo_connector.fetch_vendor_bills() uses it as invoice_number —
    enabling duplicate detection across Odoo and PDF sources.
    """
    vendor_id = _find_or_create_vendor(client, bill["vendor"])

    invoice_lines = [
        (0, 0, {
            "name":       line["name"],
            "quantity":   line["qty"],
            "price_unit": line["price"],
            "account_id": expense_account_id,
        })
        for line in bill["lines"]
    ]
    move_id = client.execute("account.move", "create", {
        "move_type":         "in_invoice",
        "partner_id":        vendor_id,
        "invoice_date":      bill["invoice_date"],
        "invoice_date_due":  bill.get("due_date"),
        "ref":               bill["ref"],        # vendor's invoice number
        "invoice_line_ids":  invoice_lines,
    })

    # Post the bill: draft → posted (makes it appear in accounting reports)
    client.execute("account.move", "action_post", [move_id])
    return move_id


if __name__ == "__main__":
    main()
