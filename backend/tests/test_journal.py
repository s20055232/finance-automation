"""
test_journal.py — Phase 2b 借貸分錄產生測試

=== 測試範圍 ===
  validate_balance()         — 借貸平衡檢查
  generate_journal_entries() — 主要分錄產生邏輯

=== 核心會計規則（WHY these tests exist）===
  1. 雙式記帳：每張發票的借方總計必須等於貸方總計
  2. 含稅分拆：有稅金時必須獨立記「Tax Expense」，讓財報能分離費用與稅金
  3. 帳戶選擇優先順序：
       AI 高/中信心度 → 用 Claude 建議的帳戶（更精準）
       AI 低信心度 or 關鍵字規則 → 用 config.CATEGORY_ACCOUNTS 安全預設值
  4. 可追溯性：description 必須包含廠商名稱和發票號碼，供稽核人員追查原始單據
"""
from src.journal import generate_journal_entries, validate_balance
from src.models import JournalEntry
from config import CATEGORY_ACCOUNTS


class TestValidateBalance:
    """
    借貸平衡是會計正確性的基礎。
    試算表（Trial Balance）的核心假設：所有分錄的借方總和 = 貸方總和。
    任何不平衡都代表記帳錯誤，必須在進入 Phase 3 前攔截。
    """

    def test_balanced(self):
        # 最基本情境：買電腦 $1,000
        # 借：設備（資產增加）$1,000 / 貸：現金（資產減少）$1,000
        entries = [
            JournalEntry("Equipment", "Asset", 1000.0, 0.0, "desc"),
            JournalEntry("Cash",      "Asset", 0.0, 1000.0, "desc"),
        ]
        assert validate_balance(entries) is True

    def test_unbalanced(self):
        # 貸方少記 $1 → 試算表就不會平衡，應被拒絕
        entries = [
            JournalEntry("Equipment", "Asset", 1000.0, 0.0, "desc"),
            JournalEntry("Cash",      "Asset", 0.0,   999.0, "desc"),
        ]
        assert validate_balance(entries) is False

    def test_floating_point_tolerance(self):
        # 浮點數運算（如 $100.10 - $0.10）可能產生 $99.9999... 而非 $100.0
        # 允許 $0.01 以內的誤差，避免把正確分錄誤判為不平衡
        entries = [
            JournalEntry("Equipment", "Asset", 100.001, 0.0,   "desc"),
            JournalEntry("Cash",      "Asset", 0.0,   100.0, "desc"),
        ]
        assert validate_balance(entries) is True


class TestGenerateJournalEntries:
    """
    測試分錄產生的完整業務邏輯。

    分錄結構取決於兩個維度：
      - 是否含稅（tax_amount > 0）→ 決定分錄筆數
      - AI 信心度 + 來源        → 決定帳戶名稱
    """

    # ── 無稅金發票（2 筆分錄）────────────────────────────────────────────────

    def test_no_tax_produces_two_entries(self, invoice_no_tax, classification_high):
        # 無稅時只需要借（費用）和貸（現金）兩筆，結構最簡單
        entries = generate_journal_entries(invoice_no_tax, classification_high)
        assert len(entries) == 2

    def test_no_tax_amounts(self, invoice_no_tax, classification_high):
        # 借方記全額，貸方也記全額，且只有其中一方有金額（另一方為 0）
        # 這是雙式記帳的規範：每筆分錄要麼是借、要麼是貸，不能兩邊都有金額
        entries = generate_journal_entries(invoice_no_tax, classification_high)
        assert entries[0].debit_amount == 1999.0   # 借：設備
        assert entries[0].credit_amount == 0.0
        assert entries[1].debit_amount == 0.0
        assert entries[1].credit_amount == 1999.0  # 貸：現金

    def test_no_tax_is_balanced(self, invoice_no_tax, classification_high):
        entries = generate_journal_entries(invoice_no_tax, classification_high)
        assert validate_balance(entries)

    # ── 含稅發票（3 筆分錄）─────────────────────────────────────────────────

    def test_with_tax_produces_three_entries(self, invoice_with_tax, classification_high):
        # 含稅時必須拆成 3 筆：費用（稅前）、稅金、貸方（稅後全額）
        # 目的：讓財報可以分別統計「費用」和「稅金」，符合稅務申報需求
        cls = {**classification_high, "expense_category": "utilities",
               "suggested_debit_account": "Utilities Expense"}
        entries = generate_journal_entries(invoice_with_tax, cls)
        assert len(entries) == 3

    def test_with_tax_middle_entry_is_tax(self, invoice_with_tax, classification_high):
        # 第 2 筆必須是 Tax Expense，金額等於發票上的稅金欄位
        # 電費 $450 + 稅 $49.5 → Tax Expense 借方 $49.5
        cls = {**classification_high, "expense_category": "utilities",
               "suggested_debit_account": "Utilities Expense"}
        entries = generate_journal_entries(invoice_with_tax, cls)
        assert entries[1].account_name == "Tax Expense"
        assert entries[1].debit_amount == 49.5

    def test_with_tax_credit_is_total(self, invoice_with_tax, classification_high):
        # 貸方（現金流出）必須是含稅全額，因為實際付出去的錢包含稅金
        cls = {**classification_high, "expense_category": "utilities",
               "suggested_debit_account": "Utilities Expense"}
        entries = generate_journal_entries(invoice_with_tax, cls)
        assert entries[2].credit_amount == 499.5   # $450 + $49.5

    def test_with_tax_is_balanced(self, invoice_with_tax, classification_high):
        # 3 筆分錄的借方總計（$450 + $49.5）必須等於貸方總計（$499.5）
        cls = {**classification_high, "expense_category": "utilities",
               "suggested_debit_account": "Utilities Expense"}
        entries = generate_journal_entries(invoice_with_tax, cls)
        assert validate_balance(entries)

    # ── 帳戶選擇邏輯 ─────────────────────────────────────────────────────────

    def test_high_confidence_uses_ai_accounts(self, invoice_no_tax, classification_high):
        # AI 高信心度 → 信任 Claude 建議的帳戶（更精準反映實際用途）
        # 例：Claude 判定是「設備採購」→ 借 Equipment / 貸 Cash
        entries = generate_journal_entries(invoice_no_tax, classification_high)
        assert entries[0].account_name == "Equipment"
        assert entries[1].account_name == "Cash"

    def test_low_confidence_uses_category_fallback(self, invoice_no_tax, classification_low):
        # AI 低信心度 → 不信任 Claude 的帳戶建議，改用 CATEGORY_ACCOUNTS 安全預設值
        # 這避免了「AI 猜錯帳戶 → 財報錯誤」的風險
        # fixture classification_low 的 expense_category = "software"
        entries = generate_journal_entries(invoice_no_tax, classification_low)
        expected = CATEGORY_ACCOUNTS["software"]
        assert entries[0].account_name == expected["debit"]   # Software/SaaS Expense
        assert entries[1].account_name == expected["credit"]  # Cash

    def test_fallback_source_uses_category_accounts(self, invoice_no_tax):
        # 即使 confidence 是 "high"，只要 source 是 "fallback_rules"（關鍵字分類）
        # 就不使用 suggested 帳戶 — 因為帳戶建議本身也是來自規則而非 AI
        cls = {
            "expense_category": "rent",
            "classification_confidence": "high",        # high，但來源是關鍵字規則
            "classification_source": "fallback_rules",  # ← 這個才是判斷關鍵
            "suggested_debit_account": "IGNORE THIS",
            "suggested_credit_account": "IGNORE THIS",
        }
        entries = generate_journal_entries(invoice_no_tax, cls)
        assert entries[0].account_name == CATEGORY_ACCOUNTS["rent"]["debit"]  # Rent Expense

    # ── 可追溯性 ─────────────────────────────────────────────────────────────

    def test_description_format(self, invoice_no_tax, classification_high):
        # 稽核人員看到分錄時，必須能從 description 直接找到對應的原始發票
        # 格式："{category} expense: {vendor_name} ({invoice_number})"
        entries = generate_journal_entries(invoice_no_tax, classification_high)
        assert "Acme Tech" in entries[0].description
        assert "INV-TEST-001" in entries[0].description

    # ── 防禦性行為 ───────────────────────────────────────────────────────────

    def test_unknown_category_falls_back_to_other(self, invoice_no_tax):
        # 萬一 AI 回傳了 config.EXPENSE_CATEGORIES 之外的類別
        # → 使用 "other"（Miscellaneous Expense）作為最後防線
        # 這確保系統不會因為未知類別而崩潰，頂多產生一筆需要人工確認的雜費分錄
        cls = {
            "expense_category": "nonexistent_category",
            "classification_confidence": "low",
            "classification_source": "fallback_rules",
            "suggested_debit_account": "X",
            "suggested_credit_account": "Y",
        }
        entries = generate_journal_entries(invoice_no_tax, cls)
        assert entries[0].account_name == CATEGORY_ACCOUNTS["other"]["debit"]  # Miscellaneous Expense
