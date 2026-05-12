"""
config.py — 系統設定與會計基礎知識

=== 給新手的會計小教室 ===

【什麼是會計分錄（Journal Entry）？】
每一筆花費，在會計上都要記兩次，這叫做「複式記帳」。
就像你把錢從左口袋移到右口袋，左邊少了，右邊多了，兩邊加起來永遠相等。

  借方（Debit）= 錢「去了哪裡」（資產增加 or 費用發生）
  貸方（Credit）= 錢「從哪來的」（資產減少 or 負債增加）

範例：公司買一台 MacBook $50,000
  借：電腦設備（資產增加） $50,000
  貸：現金（資產減少）     $50,000
→ 總借 = 總貸，永遠平衡！這就是「借貸平衡」原則。

【什麼是費用類別（Expense Category）？】
公司的每一筆支出都要分類，方便做財報。
例如：租金、水電費、廣告費、設備費…分類清楚才知道錢花在哪。

【什麼是試算表（Trial Balance）？】
把所有帳戶的借貸合計列出來，確認「總借 = 總貸 = 0」。
如果不等，代表某地方記錯了，要找出異常！

【什麼是損益表（Income Statement）？】
一段期間內：收入 - 費用 = 淨利（或淨損）
這張報表讓老闆知道公司這個月是賺錢還是虧錢。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
SAMPLE_DATA_DIR = BASE_DIR / "sample_data" / "invoices"   # 範例發票 PDF 放這裡
OUTPUT_DIR = BASE_DIR / "output"                           # 產生的 Excel 報表放這裡
INPUT_DIR = BASE_DIR / "input"                             # 生產模式：新發票丟這裡自動處理

for _d in (OUTPUT_DIR, INPUT_DIR, SAMPLE_DATA_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── AI 設定 ───────────────────────────────────────────────────────────────────
# Gemini 2.5 Flash：速度快、成本低，適合發票分類
# Gemini 2.5 Pro：準確度最高，適合複雜推理
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.5-flash")
AI_MAX_TOKENS = 1024
AI_TIMEOUT = 30.0

# ── Ollama 本地 LLM（優先於 Gemini，設定 OLLAMA_MODEL 後自動切換）────────────────
# 先 pull model：ollama pull gemma4:1b
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "")   # e.g. "gemma4:1b"

# ── 對帳異常閾值 ──────────────────────────────────────────────────────────────
# 單張發票超過這個金額 → 標記警告，提醒財務人員人工複核
LARGE_AMOUNT_THRESHOLD = float(os.getenv("LARGE_AMOUNT_THRESHOLD", "10000"))
# 同一廠商在幾天內出現金額相似的發票 → 可能是重複請款
DUPLICATE_WINDOW_DAYS = int(os.getenv("DUPLICATE_WINDOW_DAYS", "30"))

# ── 電子郵件警報設定 ──────────────────────────────────────────────────────────
# EMAIL_DRY_RUN=true 時只會在終端機印出「假設要寄的內容」，不會真的發信
EMAIL_DRY_RUN = os.getenv("EMAIL_DRY_RUN", "true").lower() == "true"
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# ── 費用類別清單 ──────────────────────────────────────────────────────────────
# Claude AI 會把每張發票分到以下其中一個類別
# 這些類別對應到財報上的費用科目
EXPENSE_CATEGORIES = [
    "rent",        # 租金費用（辦公室、倉庫）
    "equipment",   # 設備採購（電腦、機器，使用年限 > 1 年）
    "marketing",   # 行銷廣告（Google Ads、FB、公關）
    "utilities",   # 水電網路（電費、瓦斯、網路月租）
    "supplies",    # 辦公耗材（影印紙、墨水匣、文具）
    "services",    # 專業服務（律師、顧問、外包工程師）
    "software",    # 軟體訂閱（SaaS、雲端、授權費）
    "salaries",    # 薪資（員工薪水、獎金）
    "travel",      # 差旅費（機票、飯店、計程車）
    "insurance",   # 保險費（商業保險）
    "other",       # 其他（無法歸類時使用）
]

# ── 分錄對照表：每個費用類別 → 自動產生借貸帳戶 ──────────────────────────────
#
# 這裡定義了「複式記帳」的核心邏輯：
#   "debit"  = 借方帳戶（花費的地方，費用或資產增加）
#   "credit" = 貸方帳戶（錢從哪來，通常是現金或應付帳款減少）
#
# 範例解讀：
#   rent → 借：租金費用（費用發生）/ 貸：現金（付出去了）
#   equipment → 借：設備（資產增加）/ 貸：現金（付出去了）
#   services → 借：專業服務費（費用）/ 貸：應付帳款（還沒付，先記負債）
#
CATEGORY_ACCOUNTS: dict[str, dict[str, str]] = {
    "rent":      {"debit": "Rent Expense",          "credit": "Cash"},
    "equipment": {"debit": "Equipment",              "credit": "Cash"},
    "marketing": {"debit": "Marketing Expense",      "credit": "Cash"},
    "utilities": {"debit": "Utilities Expense",      "credit": "Cash"},
    "supplies":  {"debit": "Office Supplies",         "credit": "Cash"},
    "services":  {"debit": "Professional Services",   "credit": "Accounts Payable"},
    "software":  {"debit": "Software/SaaS Expense",   "credit": "Cash"},
    "salaries":  {"debit": "Salaries Expense",        "credit": "Cash"},
    "travel":    {"debit": "Travel Expense",          "credit": "Cash"},
    "insurance": {"debit": "Insurance Expense",       "credit": "Cash"},
    "other":     {"debit": "Miscellaneous Expense",   "credit": "Cash"},
}

# ── 帳戶類型對照：用於試算表分類與損益表計算 ──────────────────────────────────
#
# 會計五大帳戶類型：
#   Asset（資產）    = 公司擁有的東西（現金、設備、應收帳款）
#   Liability（負債）= 公司欠別人的（應付帳款、借款）
#   Equity（權益）   = 股東的份額（股本、保留盈餘）
#   Expense（費用）  = 花掉的成本（租金、廣告、薪資）
#   Revenue（收入）  = 賺進來的錢（銷售收入、服務費）
#
# 損益表公式：Revenue - Expense = Net Income（淨利）
# 試算表平衡：Total Debits = Total Credits（借方總計 = 貸方總計）
#
ACCOUNT_TYPES: dict[str, str] = {
    "Cash":                   "Asset",
    "Equipment":              "Asset",
    "Accounts Receivable":    "Asset",
    "Accounts Payable":       "Liability",
    "Rent Expense":           "Expense",
    "Marketing Expense":      "Expense",
    "Utilities Expense":      "Expense",
    "Office Supplies":        "Expense",
    "Professional Services":  "Expense",
    "Software/SaaS Expense":  "Expense",
    "Salaries Expense":       "Expense",
    "Travel Expense":         "Expense",
    "Insurance Expense":      "Expense",
    "Miscellaneous Expense":  "Expense",
    "Sales Revenue":          "Revenue",
    "Service Revenue":        "Revenue",
}
