"""
test_odoo_connector.py — Odoo XML-RPC 整合測試

=== 測試策略 ===
所有測試都使用 Mock，不需要真實的 Odoo 執行個體。

Mock 的必要性：
  - Odoo XML-RPC 呼叫是 I/O 操作（網路請求），在單元測試中不應有外部依賴
  - 用 mock_client.execute.side_effect 模擬 Odoo 回傳的 XML-RPC 資料結構
  - 測試邏輯（欄位對應、資料轉換）而非 Odoo 本身

=== Odoo 資料結構說明 ===
  many2one 欄位（如 partner_id、currency_id）回傳的是 [id, name] 的 list
  例：partner_id = [10, "Acme Tech"]  → 取 [1] 得到廠商名稱

=== 測試範圍 ===
  get_client()            — graceful degradation（無 API key 時不崩潰）
  fetch_vendor_bills()    — Odoo bill → InvoiceData 轉換
  write_journal_entries() — JournalEntry → Odoo account.move 寫回
"""
import pytest
from unittest.mock import MagicMock, patch
from src.odoo_connector import (
    OdooClient, get_client, fetch_vendor_bills, write_journal_entries,
    _find_account, _find_journal,
)
from src.models import InvoiceData, JournalEntry


@pytest.fixture(autouse=True)
def clear_lru_caches():
    """
    每個 test 前強制清除 lru_cache。

    _find_account / _find_journal 使用 lru_cache 避免重複查詢 Odoo。
    若不清除，前一個 test 的 mock 結果會被帶入下一個 test，
    導致測試間互相污染，出現難以追查的 flaky test。
    """
    _find_account.cache_clear()
    _find_journal.cache_clear()
    yield


@pytest.fixture
def mock_client():
    """
    模擬已驗證的 OdooClient。

    spec=OdooClient 確保只有 OdooClient 上存在的屬性和方法可以被呼叫，
    避免 Mock 因為過於寬鬆而掩蓋拼字錯誤等 bug。
    execute() 的回傳值由各 test 透過 side_effect 控制。
    """
    client = MagicMock(spec=OdooClient)
    client.uid = 1
    client.db = "odoo"
    client.api_key = "test-key"
    return client


class TestGetClient:
    """
    get_client() 是 Odoo 整合的入口。
    核心設計：ODOO_API_KEY 未設定時回傳 None，
    讓 demo.py 可以安全地跳過 Odoo 來源，只跑 PDF pipeline。
    這樣部署到 fly.io 時，沒有 Odoo 的環境仍然可以正常運作。
    """

    def test_returns_none_when_no_api_key(self):
        # 最重要的 graceful degradation：環境變數未設定 → 靜默跳過
        # 不拋出例外，不印 ERROR，只印 INFO log 並回傳 None
        with patch("src.odoo_connector.ODOO_API_KEY", ""):
            result = get_client()
        assert result is None

    def test_returns_client_when_api_key_set(self):
        # API key 存在時應該嘗試連線並回傳 OdooClient 實例
        with patch("src.odoo_connector.ODOO_API_KEY", "fake-key"), \
             patch("src.odoo_connector.OdooClient") as MockClient:
            MockClient.return_value = MagicMock()
            result = get_client()
        assert result is not None

    def test_returns_none_on_connection_error(self):
        # Odoo 無法連線（如 Docker 沒啟動）→ 回傳 None 而非讓程式崩潰
        # 這讓 demo 在 Odoo 掛掉時仍能繼續跑 PDF pipeline
        with patch("src.odoo_connector.ODOO_API_KEY", "fake-key"), \
             patch("src.odoo_connector.OdooClient", side_effect=Exception("timeout")):
            result = get_client()
        assert result is None


class TestFetchVendorBills:
    """
    fetch_vendor_bills() 讀取 Odoo 的廠商發票（vendor bills）並轉成 InvoiceData。

    Odoo XML-RPC 呼叫順序：
      1. account.move search_read → 取得發票清單（含 invoice_line_ids）
      2. account.move.line read   → 取得每張發票的明細行

    mock_client.execute.side_effect 是一個 list，每次呼叫 execute() 會依序取出。
    """

    def test_returns_invoicedata_list(self, mock_client):
        # 正常情境：一張發票，一個明細行
        # 驗證 Odoo XML-RPC 欄位到 InvoiceData 的對應是否正確
        mock_client.execute.side_effect = [
            # 第 1 次 execute：account.move search_read
            # partner_id 是 [id, name] 的 many2one tuple
            [{
                "id": 42,
                "name": "BILL/2024/001",
                "partner_id": [10, "Acme Tech"],
                "invoice_date": "2024-01-15",
                "invoice_date_due": "2024-02-15",
                "amount_untaxed": 1999.0,
                "amount_tax": 0.0,
                "amount_total": 1999.0,
                "currency_id": [1, "USD"],
                "invoice_line_ids": [101],
            }],
            # 第 2 次 execute：account.move.line read
            [{
                "id": 101,
                "name": "MacBook Pro",
                "quantity": 1.0,
                "price_unit": 1999.0,
                "price_subtotal": 1999.0,
                "exclude_from_invoice_tab": False,
            }],
        ]

        invoices = fetch_vendor_bills(mock_client)

        assert len(invoices) == 1
        inv = invoices[0]
        assert isinstance(inv, InvoiceData)
        assert inv.invoice_number == "BILL/2024/001"
        assert inv.vendor_name == "Acme Tech"       # 從 partner_id[1] 取出
        assert inv.total_amount == 1999.0
        assert inv.extraction_method == "odoo_xmlrpc"
        assert inv.source_file == "odoo:42"          # 格式："odoo:{id}"，用於追蹤來源

    def test_missing_partner_falls_back_to_unknown_vendor(self, mock_client):
        # Odoo 允許 partner_id 為 False（未指定廠商的草稿發票）
        # 這種情況不應拋出 KeyError，而是優雅地用 "Unknown Vendor" 替代
        # 讓這張發票仍然進入 pipeline，最終在 reconciler 標記為 warning
        mock_client.execute.side_effect = [
            [{"id": 99, "partner_id": False, "name": "BILL/X",
              "invoice_date": "2024-01-01", "invoice_date_due": None,
              "amount_untaxed": 100.0, "amount_tax": 0.0, "amount_total": 100.0,
              "currency_id": [1, "USD"], "invoice_line_ids": []}],
        ]
        invoices = fetch_vendor_bills(mock_client)
        assert len(invoices) == 1
        assert invoices[0].vendor_name == "Unknown Vendor"

    def test_skips_bill_that_raises(self, mock_client):
        # 單張發票處理失敗（如 DB 錯誤）→ 記 warning log 並跳過，繼續處理其他發票
        # 不因為一張壞掉的發票而中斷整批次處理
        mock_client.execute.side_effect = [
            [{"id": 99, "partner_id": [1, "Vendor"], "name": "BILL/ERR",
              "invoice_date": "2024-01-01", "invoice_date_due": None,
              "amount_untaxed": 100.0, "amount_tax": 0.0, "amount_total": 100.0,
              "currency_id": [1, "USD"], "invoice_line_ids": [99]}],
            Exception("DB error"),  # 第 2 次 execute（讀明細）拋出例外
        ]
        invoices = fetch_vendor_bills(mock_client)
        assert invoices == []

    def test_excludes_tax_lines(self, mock_client):
        # Odoo 的 account.move.line 同時包含「商品行」和「稅金行」
        # exclude_from_invoice_tab=True 的行是稅金計算行，不是實際購買項目
        # 我們只需要商品行（明細），稅金已經在 amount_tax 欄位中
        mock_client.execute.side_effect = [
            [{
                "id": 1, "name": "BILL/001",
                "partner_id": [1, "Vendor"], "invoice_date": "2024-01-01",
                "invoice_date_due": None, "amount_untaxed": 100.0,
                "amount_tax": 10.0, "amount_total": 110.0,
                "currency_id": [1, "USD"], "invoice_line_ids": [1, 2],
            }],
            [
                {"id": 1, "name": "Service Fee", "quantity": 1.0,
                 "price_unit": 100.0, "price_subtotal": 100.0,
                 "exclude_from_invoice_tab": False},     # ← 商品行，應保留
                {"id": 2, "name": "Tax 10%", "quantity": 1.0,
                 "price_unit": 10.0, "price_subtotal": 10.0,
                 "exclude_from_invoice_tab": True},      # ← 稅金行，應過濾掉
            ],
        ]
        invoices = fetch_vendor_bills(mock_client)
        assert len(invoices[0].line_items) == 1
        assert invoices[0].line_items[0].description == "Service Fee"


class TestWriteJournalEntries:
    """
    write_journal_entries() 把 AI 產生的 JournalEntry 寫回 Odoo。

    Odoo XML-RPC 呼叫順序：
      1. account.journal search_read → 找日記帳 ID
      2. account.account search_read → 找每個帳戶 ID（每個帳戶名稱查一次）
      3. account.move create         → 建立 journal entry
      4. account.move action_post    → 確認（post）分錄，使其生效

    帳戶名稱（如 "Equipment"）→ Odoo account ID 的對應靠 _find_account() 完成，
    結果被 lru_cache 快取，同一 session 內不重複查詢。
    """

    def test_creates_and_posts_move(self, mock_client, invoice_no_tax):
        # 完整寫回流程：2 筆分錄 → 建立 move → 確認
        # 驗證：回傳的 move_id 正確，且 action_post 被呼叫
        entries = [
            JournalEntry("Equipment", "Asset", 1999.0, 0.0, "Equipment purchase"),
            JournalEntry("Cash",      "Asset", 0.0, 1999.0, "Equipment purchase"),
        ]

        mock_client.execute.side_effect = [
            [{"id": 5, "name": "Miscellaneous Operations"}],  # _find_journal
            [{"id": 100, "name": "Equipment"}],               # _find_account Equipment
            [{"id": 101, "name": "Cash"}],                    # _find_account Cash
            42,                                               # create → 回傳新 move id
            None,                                             # action_post
        ]

        move_id = write_journal_entries(mock_client, invoice_no_tax, entries)
        assert move_id == 42

        # 確認 action_post 確實以正確的 move_id 被呼叫
        # 若漏掉 action_post，分錄只是草稿，不會出現在 Odoo 的試算表中
        post_call = mock_client.execute.call_args_list[-1]
        assert post_call.args[1] == "action_post"
        assert 42 in post_call.args[2]

    def test_raises_when_no_accounts_found(self, mock_client, invoice_no_tax):
        # 若所有帳戶名稱在 Odoo chart of accounts 中都找不到對應
        # → 拋出 ValueError 並提示用戶去 Odoo 新增帳戶
        # 這比靜默跳過更好：靜默跳過會產生空的 journal entry，財報就不平衡了
        entries = [
            JournalEntry("Unknown Account", "Expense", 100.0, 0.0, "test"),
            JournalEntry("Unknown Credit",  "Asset",   0.0, 100.0, "test"),
        ]
        mock_client.execute.side_effect = [
            [{"id": 5, "name": "Miscellaneous Operations"}],  # _find_journal
            [],   # _find_account → 找不到 "Unknown Account"
            [],   # _find_account → 找不到 "Unknown Credit"
        ]

        with pytest.raises(ValueError, match="No matching Odoo accounts"):
            write_journal_entries(mock_client, invoice_no_tax, entries)
