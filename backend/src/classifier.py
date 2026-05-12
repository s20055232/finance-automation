"""
classifier.py — Phase 2a：用 Gemini API 將發票分類到費用科目

=== Fallback 機制 ===
Gemini API 不可用時（無網路、無 API key、rate limit），
自動切換到關鍵字規則分類（速度快，但準確度較低）。
"""

import json
import logging
from typing import Optional

from google import genai
from google.genai import types
from openai import OpenAI

from src.models import InvoiceData
from config import (
    AI_MODEL, AI_MAX_TOKENS,
    GEMINI_API_KEY,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    EXPENSE_CATEGORIES, CATEGORY_ACCOUNTS,
)

logger = logging.getLogger(__name__)

# ── Gemini API Client（單例）──────────────────────────────────────────────────
_gemini_client: Optional[genai.Client] = None

def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


# ── Ollama Client（單例，無需 auth）──────────────────────────────────────────
_ollama_client: Optional[OpenAI] = None

def _get_ollama_client() -> OpenAI:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    return _ollama_client


# ── System Prompt（費用分類規則）────────────────────────────────────────────────
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
    OLLAMA_MODEL 設定時優先用本地 Ollama，否則用 Gemini API，
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

    try:
        result = _call_gemini(invoice)
        result["classification_source"] = "ai"
        return result
    except Exception as e:
        logger.warning("Gemini API error for %s: %s", invoice.invoice_number, e)

    return fallback_classify(invoice)


def classify_batch(invoices: list[InvoiceData]) -> list[dict]:
    """批次分類（Ollama 優先，否則 Gemini API）。"""
    results = []

    for i, invoice in enumerate(invoices, 1):
        if OLLAMA_MODEL:
            try:
                result = _call_ollama(invoice)
                result["classification_source"] = "ai"
            except Exception as e:
                logger.warning("[%d/%d] %s — Ollama error, using fallback: %s",
                               i, len(invoices), invoice.invoice_number, e)
                result = fallback_classify(invoice)
        else:
            try:
                result = _call_gemini(invoice)
                result["classification_source"] = "ai"
            except Exception as e:
                logger.warning("[%d/%d] %s — Gemini error, using fallback: %s",
                               i, len(invoices), invoice.invoice_number, e)
                result = fallback_classify(invoice)

        results.append(result)
        logger.info("[%d/%d] %s → %s (%s)",
                    i, len(invoices), invoice.invoice_number,
                    result["expense_category"], result["classification_source"])

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


def _call_gemini(invoice: InvoiceData) -> dict:
    """呼叫 Gemini API 並解析回傳的 JSON。"""
    client = _get_gemini_client()

    response = client.models.generate_content(
        model=AI_MODEL,
        contents=_build_user_prompt(invoice),
        config=types.GenerateContentConfig(
            system_instruction=CLASSIFICATION_SYSTEM_PROMPT,
            max_output_tokens=AI_MAX_TOKENS,
            temperature=0.1,
        ),
    )

    text = (response.text or "").strip()

    # 移除可能的 markdown code fence
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    result = json.loads(text)

    category = result.get("expense_category", "other")
    if category not in EXPENSE_CATEGORIES:
        logger.warning("Gemini returned unknown category '%s', defaulting to 'other'", category)
        result["expense_category"] = "other"

    accounts = CATEGORY_ACCOUNTS.get(result["expense_category"], CATEGORY_ACCOUNTS["other"])
    result.setdefault("suggested_debit_account",  accounts["debit"])
    result.setdefault("suggested_credit_account", accounts["credit"])
    result.setdefault("expense_subcategory",       "general")
    result.setdefault("classification_confidence", "medium")
    result.setdefault("ai_reasoning", "")

    return result
