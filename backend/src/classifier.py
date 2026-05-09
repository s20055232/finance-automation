"""
classifier.py — Phase 2a：用 Claude API 將發票分類到費用科目

=== Prompt Caching 說明 ===
每次 API 呼叫都需要把「費用分類規則」帶進 system prompt。
這份規則文字很長（約 2000+ tokens），但幾乎不會改變。

做法：在 system prompt block 加上 cache_control: {type: "ephemeral"}
第一次呼叫：Claude 讀取全部 tokens（慢，費用正常）
後續呼叫：直接從 cache 讀取 system prompt（快，費用約 1/10）

可從 response.usage.cache_read_input_tokens 確認是否有 cache hit。

=== Fallback 機制 ===
Claude API 不可用時（無網路、無 API key、rate limit），
自動切換到關鍵字規則分類（速度快，但準確度較低）。
"""

import json
import time
import logging
from typing import Optional

import anthropic
from openai import OpenAI

from src.models import InvoiceData
from config import (
    AI_MODEL, AI_MAX_TOKENS, AI_TIMEOUT,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL,
    EXPENSE_CATEGORIES, CATEGORY_ACCOUNTS,
)

logger = logging.getLogger(__name__)

# ── Claude API Client（單例）──────────────────────────────────────────────────
_client: Optional[anthropic.Anthropic] = None

def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# ── Ollama Client（單例，無需 auth）──────────────────────────────────────────
_ollama_client: Optional[OpenAI] = None

def _get_ollama_client() -> OpenAI:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    return _ollama_client


# ── NVIDIA NIM Client（單例）─────────────────────────────────────────────────
_nvidia_client: Optional[OpenAI] = None

def _get_nvidia_client() -> OpenAI:
    global _nvidia_client
    if _nvidia_client is None:
        _nvidia_client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)
    return _nvidia_client


# ── System Prompt（費用分類規則，會被 cache）─────────────────────────────────────
#
# 這份 prompt 需要超過 2048 tokens 才能在 Sonnet 4.6 上觸發 cache。
# 詳細的規則描述有助於：
#   1. 讓 cache 效果最大化（prompt 越長，cache 節省越多）
#   2. 提高分類準確度（規則越清楚，模型越少猜測）
#
CLASSIFICATION_SYSTEM_PROMPT = """You are an expert accountant specializing in expense classification for small to medium businesses. Your task is to analyze invoice data and classify expenses into the correct accounting categories.

## Your Role
You examine invoice details (vendor name, line items, amounts, dates) and determine:
1. The correct expense category from the approved list
2. A subcategory for more granular reporting
3. Your confidence level in the classification
4. The appropriate debit and credit accounts for double-entry bookkeeping

## Approved Expense Categories

### 1. rent
Definition: Payments for use of physical space — office, warehouse, retail, parking.
Examples: Monthly office rent, storage unit fees, co-working space memberships, parking lot fees.
Subcategories: office_rent, warehouse_rent, retail_space, parking, coworking.
Debit account: Rent Expense | Credit account: Cash or Accounts Payable
Key signals: vendor names containing "properties", "realty", "spaces", "plaza", "tower", "office park"; line items mentioning "rent", "lease", "occupancy".
NOT this category: equipment leases (use equipment), software subscriptions (use software), vehicle leases (use travel).

### 2. equipment
Definition: Purchase of tangible assets with useful life greater than one year. These become assets on the balance sheet, not immediate expenses.
Examples: Computers, servers, office furniture, manufacturing machinery, laboratory instruments, printers, cameras, monitors.
Subcategories: computer_hardware, furniture, machinery, laboratory, networking, audio_visual.
Debit account: Equipment (Asset) | Credit account: Cash or Accounts Payable
Key signals: product names like "MacBook", "Dell", "HP", "server rack", "desk", "chair", "workstation"; quantities with unit prices over $500.
NOT this category: software (use software), repairs to equipment (use services), consumable supplies (use supplies).

### 3. marketing
Definition: Expenses directly related to promoting products or services and acquiring customers.
Examples: Digital advertising (Google Ads, Meta Ads, LinkedIn), print advertising, PR agency fees, trade show booth rentals, promotional merchandise, influencer payments, SEO services, content creation.
Subcategories: digital_advertising, print_advertising, pr_and_communications, events_and_tradeshows, promotional_materials, agency_fees.
Debit account: Marketing Expense | Credit account: Cash or Accounts Payable
Key signals: vendor names containing "media", "agency", "advertising", "marketing", "PR", "communications", "digital"; line items mentioning "ads", "campaigns", "impressions", "clicks", "SEO", "social media".

### 4. utilities
Definition: Essential services for operating a business location — electricity, gas, water, internet, phone.
Examples: Electric bills, gas bills, water and sewer, business internet service, landline phone service, trash collection.
Subcategories: electricity, gas, water_sewer, internet, telephone, waste_management.
Debit account: Utilities Expense | Credit account: Cash
Key signals: vendor names like "power", "electric", "gas", "water", "utility", "telecom", "internet", "fiber"; line items mentioning "kwh", "therm", "service charge", "monthly service".
NOT this category: mobile phone for personal use, streaming services (use software).

### 5. supplies
Definition: Consumable items used in day-to-day operations that are expensed immediately (not capitalized).
Examples: Printer paper, pens, toner cartridges, cleaning supplies, coffee and break room supplies, first aid kits, packaging materials, postage stamps.
Subcategories: office_supplies, cleaning_supplies, break_room, packaging, postage, safety_supplies.
Debit account: Office Supplies | Credit account: Cash or Accounts Payable
Key signals: vendor names like "Staples", "Office Depot", "Amazon" (for small items), "Uline"; line items for quantities of inexpensive consumable items.
NOT this category: items over $500 per unit (likely equipment), food for client entertainment (use services or travel).

### 6. services
Definition: Professional or specialized services provided by external parties — consulting, legal, accounting, outsourced labor.
Examples: Legal fees, CPA/accounting fees, IT consulting, management consulting, recruiting fees, outsourced customer service, janitorial services, security services, graphic design.
Subcategories: legal, accounting, it_consulting, management_consulting, recruiting, outsourced_labor, janitorial, security, design.
Debit account: Professional Services | Credit account: Cash or Accounts Payable
Key signals: vendor names containing "consulting", "associates", "partners", "law", "legal", "CPA", "accounting", "advisors"; line items with hourly rates or project fees.

### 7. software
Definition: Software licenses, subscriptions, and SaaS products used in business operations.
Examples: Microsoft 365, Google Workspace, Slack, Zoom, Salesforce, AWS, GitHub, Adobe Creative Cloud, QuickBooks, antivirus, project management tools.
Subcategories: productivity_suite, communication, crm, cloud_infrastructure, development_tools, design_tools, accounting_software, security, project_management.
Debit account: Software/SaaS Expense | Credit account: Cash or Accounts Payable
Key signals: vendor names like "Microsoft", "Google", "Slack", "Zoom", "AWS", "Salesforce", "Adobe", "GitHub", "Atlassian"; line items mentioning "license", "subscription", "per seat", "annual plan", "monthly plan".
NOT this category: hardware (use equipment), software development services (use services).

### 8. salaries
Definition: Compensation paid to employees — wages, salaries, bonuses, commissions. Also includes payroll processing fees.
Examples: Monthly salary payments, hourly wages, performance bonuses, sales commissions, payroll service fees (e.g., ADP, Paychex).
Subcategories: base_salary, hourly_wages, bonus_commission, payroll_processing.
Debit account: Salaries Expense | Credit account: Cash
Key signals: vendor names like "ADP", "Paychex", "Gusto", "payroll"; line items mentioning "salary", "wages", "payroll", "compensation", "bonus".
NOT this category: contractor payments (use services), staffing agency fees where workers are not employees.

### 9. travel
Definition: Business-related travel expenses for employees.
Examples: Airfare, hotel stays, car rentals, taxi/Uber/Lyft, train tickets, meals during travel, conference registration fees, parking at airports.
Subcategories: airfare, accommodation, ground_transportation, meals_during_travel, conference_registration, parking.
Debit account: Travel Expense | Credit account: Cash or Accounts Payable (or Credit Card Payable)
Key signals: vendor names like airlines, hotels, Uber, Lyft, Airbnb, rental car companies, Expedia, conference names; line items mentioning "flight", "hotel", "per diem", "transportation".
NOT this category: commuting expenses (generally not deductible), permanent relocation costs.

### 10. insurance
Definition: Premiums paid for business insurance policies.
Examples: General liability insurance, professional liability (E&O), workers compensation, property insurance, business interruption insurance, cyber liability, directors and officers (D&O) insurance, vehicle insurance for business vehicles.
Subcategories: general_liability, professional_liability, workers_compensation, property, business_interruption, cyber_liability, vehicle.
Debit account: Insurance Expense | Credit account: Cash or Prepaid Insurance
Key signals: vendor names containing "insurance", "assurance", "mutual", "Hartford", "Chubb", "Travelers", "Hiscox"; line items mentioning "premium", "policy", "coverage".

### 11. other
Definition: Expenses that do not fit clearly into any of the above categories. Use this only when no other category applies.
Examples: Bank charges and fees, credit card processing fees, charitable donations (if business-related), fines and penalties (though usually not tax-deductible), subscriptions to industry publications, miscellaneous.
Subcategories: bank_fees, payment_processing, donations, fines_penalties, subscriptions, miscellaneous.
Debit account: Miscellaneous Expense | Credit account: Cash or Accounts Payable

## Classification Rules

1. SPECIFICITY: Always choose the most specific category that applies. If a vendor sells both software and hardware, classify based on what was actually purchased.

2. AMOUNT THRESHOLDS: Items under $100 are almost always "supplies" unless clearly a service or software subscription. Items over $1,000 per unit are likely "equipment" if they are physical goods.

3. RECURRING vs ONE-TIME: Monthly/annual fees are usually "software" (subscriptions) or "rent". One-time payments for physical goods are "equipment" or "supplies".

4. VENDOR vs LINE ITEMS: Prioritize line item descriptions over vendor names. A vendor named "Amazon" might sell office supplies, equipment, or cloud services — look at what was actually purchased.

5. AMBIGUOUS CASES: When genuinely uncertain between two categories, choose the one where:
   a. The debit account would most accurately represent the economic substance
   b. Management would most likely expect to find this expense

## Output Format

Respond with a JSON object only — no markdown, no explanation outside the JSON:

{
  "expense_category": "<one of the 11 approved categories>",
  "expense_subcategory": "<subcategory string>",
  "classification_confidence": "<high|medium|low>",
  "ai_reasoning": "<1-2 sentences explaining your classification decision>",
  "suggested_debit_account": "<account name>",
  "suggested_credit_account": "<Cash|Accounts Payable>"
}

Confidence levels:
- high: Clear signals from vendor name AND line items, no ambiguity
- medium: Reasonable confidence based on available information, minor ambiguity
- low: Limited information, significant ambiguity, or invoice is unusual
"""

# ── 關鍵字規則（Fallback，不需要 API）────────────────────────────────────────────

_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("rent",      ["rent", "lease", "office space", "sq ft", "monthly rent", "landlord",
                   "realty", "properties", "real estate", "occupancy"]),
    ("equipment", ["macbook", "laptop", "computer", "server", "monitor", "printer",
                   "furniture", "desk", "chair", "workstation", "dell", "hp ", "lenovo"]),
    ("marketing", ["advertising", "ads", "google ads", "facebook ads", "meta ads",
                   "seo", "marketing", "campaign", "pr ", "public relations", "media buy"]),
    ("utilities", ["electric", "electricity", "gas bill", "water", "internet service",
                   "power & light", "utility", "telecom", "broadband", "fiber"]),
    ("supplies",  ["office supply", "stationery", "paper", "toner", "ink cartridge",
                   "cleaning", "postage", "staples", "office depot"]),
    ("software",  ["aws", "azure", "google cloud", "slack", "zoom", "microsoft 365",
                   "adobe", "salesforce", "github", "subscription", "saas", "license",
                   "per seat", "cloudstack", "software"]),
    ("services",  ["consulting", "legal", "attorney", "law firm", "accounting", "cpa",
                   "advisory", "professional service", "outsource", "contractor"]),
    ("salaries",  ["salary", "payroll", "adp", "paychex", "gusto", "wages", "bonus"]),
    ("travel",    ["airfare", "hotel", "flight", "uber", "lyft", "car rental",
                   "conference", "travel", "accommodation", "taxi"]),
    ("insurance", ["insurance", "premium", "liability", "workers comp", "coverage"]),
]


def _keyword_match(text: str) -> str:
    """在文字中尋找最符合的費用類別關鍵字。"""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for category, keywords in _KEYWORD_RULES:
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            scores[category] = hits
    if not scores:
        return "other"
    return max(scores, key=lambda c: scores[c])


# ── 公開介面 ──────────────────────────────────────────────────────────────────

def classify_invoice(invoice: InvoiceData) -> dict:
    """
    單張發票分類。
    NVIDIA_API_KEY 設定時優先用 NVIDIA NIM，否則用 Claude API，
    兩者都不可用時自動切換到關鍵字規則。
    """
    if OLLAMA_MODEL:
        try:
            result = _call_ollama(invoice)
            result["classification_source"] = "ai"
            return result
        except Exception as e:
            logger.warning("Ollama error for %s: %s", invoice.invoice_number, e)
        return fallback_classify(invoice)

    if NVIDIA_API_KEY:
        try:
            result = _call_nvidia(invoice)
            result["classification_source"] = "ai"
            return result
        except Exception as e:
            logger.warning("NVIDIA API error for %s: %s", invoice.invoice_number, e)
        return fallback_classify(invoice)

    try:
        result = _call_claude(invoice)
        result["classification_source"] = "ai"
        return result
    except anthropic.AuthenticationError:
        raise   # API key 錯誤是致命錯誤，不應 fallback
    except anthropic.RateLimitError as e:
        retry_after = int(getattr(e.response, "headers", {}).get("retry-after", "10"))
        logger.warning("Rate limited, retrying after %ds...", retry_after)
        time.sleep(retry_after)
        try:
            result = _call_claude(invoice)
            result["classification_source"] = "ai"
            return result
        except Exception:
            pass
    except Exception as e:
        logger.warning("Claude API error for %s: %s", invoice.invoice_number, e)

    return fallback_classify(invoice)


def classify_batch(invoices: list[InvoiceData]) -> list[dict]:
    """批次分類（NVIDIA NIM 優先，否則 Claude + prompt cache 統計）。"""
    results = []
    total_cache_reads = 0
    total_cache_writes = 0

    for i, invoice in enumerate(invoices, 1):
        if OLLAMA_MODEL:
            try:
                result = _call_ollama(invoice)
                result["classification_source"] = "ai"
            except Exception as e:
                logger.warning("[%d/%d] %s — Ollama error, using fallback: %s",
                               i, len(invoices), invoice.invoice_number, e)
                result = fallback_classify(invoice)
        elif NVIDIA_API_KEY:
            try:
                result = _call_nvidia(invoice)
                result["classification_source"] = "ai"
            except Exception as e:
                logger.warning("[%d/%d] %s — NVIDIA error, using fallback: %s",
                               i, len(invoices), invoice.invoice_number, e)
                result = fallback_classify(invoice)
        else:
            try:
                result = _call_claude(invoice, track_usage=True)
                result["classification_source"] = "ai"
                total_cache_reads += result.pop("_cache_read_tokens", 0)
                total_cache_writes += result.pop("_cache_write_tokens", 0)
            except anthropic.AuthenticationError:
                raise
            except Exception as e:
                logger.warning("[%d/%d] %s — Claude error, using fallback: %s",
                               i, len(invoices), invoice.invoice_number, e)
                result = fallback_classify(invoice)

        results.append(result)
        logger.info("[%d/%d] %s → %s (%s)",
                    i, len(invoices), invoice.invoice_number,
                    result["expense_category"], result["classification_source"])

    if total_cache_reads > 0 or total_cache_writes > 0:
        logger.info(
            "Prompt cache stats — writes: %d tokens, reads: %d tokens "
            "(%.0f%% cost saving on cached portion)",
            total_cache_writes, total_cache_reads,
            (total_cache_reads / max(total_cache_reads + total_cache_writes, 1)) * 100,
        )

    return results


def fallback_classify(invoice: InvoiceData) -> dict:
    """
    關鍵字規則分類（不需要 API Key）。
    準確度約 70-80%，適合展示或 API 不可用時使用。
    """
    search_text = " ".join([
        invoice.vendor_name,
        *[item.description for item in invoice.line_items],
        invoice.raw_text or "",
    ])

    category = _keyword_match(search_text)
    accounts = CATEGORY_ACCOUNTS.get(category, CATEGORY_ACCOUNTS["other"])

    return {
        "expense_category": category,
        "expense_subcategory": "general",
        "classification_confidence": "low",
        "ai_reasoning": f"Keyword-based fallback classification: matched '{category}' rules.",
        "suggested_debit_account": accounts["debit"],
        "suggested_credit_account": accounts["credit"],
        "classification_source": "fallback_rules",
    }


# ── 內部函式 ──────────────────────────────────────────────────────────────────

def _build_user_prompt(invoice: InvoiceData) -> str:
    """組裝每張發票的 user prompt（含發票基本資訊 + 明細）。"""
    line_items_text = "\n".join(
        f"  - {item.description}: qty={item.quantity}, "
        f"unit=${item.unit_price:.2f}, total=${item.amount:.2f}"
        for item in invoice.line_items[:10]   # 最多傳 10 行
    )
    if not line_items_text:
        line_items_text = "  (no line items extracted)"

    raw_excerpt = ""
    if invoice.raw_text:
        raw_excerpt = f"\nRaw text excerpt (first 500 chars):\n{invoice.raw_text[:500]}"

    return f"""Classify the following invoice:

Vendor: {invoice.vendor_name}
Invoice #: {invoice.invoice_number}
Date: {invoice.invoice_date}
Total: ${invoice.total_amount:.2f} {invoice.currency}
Subtotal: ${invoice.subtotal:.2f}
Tax: ${invoice.tax_amount:.2f}
Extraction confidence: {invoice.extraction_confidence}

Line Items:
{line_items_text}
{raw_excerpt}

Respond with a JSON object only."""


def _call_ollama(invoice: InvoiceData) -> dict:
    """呼叫本地 Ollama（OpenAI-compatible，非 streaming，低 temperature 保證 JSON 穩定）。"""
    client = _get_ollama_client()

    response = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user",   "content": _build_user_prompt(invoice)},
        ],
        temperature=0.1,
        max_tokens=AI_MAX_TOKENS,
        stream=False,
    )

    text = (response.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    result = json.loads(text)
    category = result.get("expense_category", "other")
    if category not in EXPENSE_CATEGORIES:
        result["expense_category"] = "other"

    accounts = CATEGORY_ACCOUNTS.get(result["expense_category"], CATEGORY_ACCOUNTS["other"])
    result.setdefault("suggested_debit_account",  accounts["debit"])
    result.setdefault("suggested_credit_account", accounts["credit"])
    result.setdefault("expense_subcategory",       "general")
    result.setdefault("classification_confidence", "medium")
    result.setdefault("ai_reasoning", "")
    return result


def _call_nvidia(invoice: InvoiceData) -> dict:
    """
    呼叫 NVIDIA NIM API（OpenAI-compatible，streaming）。
    收集 content chunks，略過 reasoning tokens，解析 JSON。
    """
    client = _get_nvidia_client()

    stream = client.chat.completions.create(
        model=NVIDIA_MODEL,
        messages=[
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user",   "content": _build_user_prompt(invoice)},
        ],
        temperature=1,
        top_p=0.95,
        max_tokens=16384,
        extra_body={
            "chat_template_kwargs": {
                "thinking": True,
                "reasoning_effort": "low",
            }
        },
        stream=True,
    )

    content_parts: list[str] = []
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        if delta.content is not None:
            content_parts.append(delta.content)

    text = "".join(content_parts).strip()

    # 移除可能的 markdown code fence
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    result = json.loads(text)

    category = result.get("expense_category", "other")
    if category not in EXPENSE_CATEGORIES:
        logger.warning("NVIDIA returned unknown category '%s', defaulting to 'other'", category)
        result["expense_category"] = "other"

    accounts = CATEGORY_ACCOUNTS.get(result["expense_category"], CATEGORY_ACCOUNTS["other"])
    result.setdefault("suggested_debit_account",  accounts["debit"])
    result.setdefault("suggested_credit_account", accounts["credit"])
    result.setdefault("expense_subcategory",       "general")
    result.setdefault("classification_confidence", "medium")
    result.setdefault("ai_reasoning", "")

    return result


def _call_claude(invoice: InvoiceData, track_usage: bool = False) -> dict:
    """
    呼叫 Claude API（含 prompt caching）並解析回傳的 JSON。

    System prompt 加上 cache_control，會在第一次呼叫後被 cache。
    後續同一個 session 的呼叫會直接讀 cache，費用降低約 90%。
    """
    client = _get_client()

    response = client.messages.create(
        model=AI_MODEL,
        max_tokens=AI_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": CLASSIFICATION_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},   # ← cache 就靠這個
            }
        ],
        messages=[
            {"role": "user", "content": _build_user_prompt(invoice)}
        ],
        timeout=AI_TIMEOUT,
    )

    # 取出回傳的文字（第一個 text block）
    text = next(
        (block.text for block in response.content if block.type == "text"),
        "",
    ).strip()

    # 移除可能的 markdown code fence
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    result = json.loads(text)

    # 驗證必要欄位
    category = result.get("expense_category", "other")
    if category not in EXPENSE_CATEGORIES:
        logger.warning("Claude returned unknown category '%s', defaulting to 'other'", category)
        result["expense_category"] = "other"

    # 補齊缺少的帳戶欄位（用 CATEGORY_ACCOUNTS 作為預設值）
    accounts = CATEGORY_ACCOUNTS.get(result["expense_category"], CATEGORY_ACCOUNTS["other"])
    result.setdefault("suggested_debit_account", accounts["debit"])
    result.setdefault("suggested_credit_account", accounts["credit"])
    result.setdefault("expense_subcategory", "general")
    result.setdefault("classification_confidence", "medium")
    result.setdefault("ai_reasoning", "")

    # cache 統計（供 classify_batch 使用）
    if track_usage and hasattr(response, "usage"):
        result["_cache_read_tokens"] = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        result["_cache_write_tokens"] = getattr(response.usage, "cache_creation_input_tokens", 0) or 0

    return result
