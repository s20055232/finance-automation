"""共用 fixtures"""
import pytest
from src.models import InvoiceData, LineItem


@pytest.fixture
def invoice_no_tax():
    return InvoiceData(
        invoice_number="INV-TEST-001",
        vendor_name="Acme Tech",
        invoice_date="2024-01-15",
        due_date=None,
        line_items=[LineItem("MacBook Pro", 1, 1999.0, 1999.0)],
        subtotal=1999.0,
        tax_amount=0.0,
        total_amount=1999.0,
        currency="USD",
        source_file="test.pdf",
        extraction_method="pdf_text",
        raw_text=None,
        extraction_confidence="high",
    )


@pytest.fixture
def invoice_with_tax():
    return InvoiceData(
        invoice_number="INV-TEST-002",
        vendor_name="City Power & Light",
        invoice_date="2024-01-15",
        due_date=None,
        line_items=[LineItem("Electricity", 1, 450.0, 450.0)],
        subtotal=450.0,
        tax_amount=49.5,
        total_amount=499.5,
        currency="USD",
        source_file="test.pdf",
        extraction_method="pdf_text",
        raw_text="Monthly electricity bill",
        extraction_confidence="high",
    )


@pytest.fixture
def classification_high():
    return {
        "expense_category": "equipment",
        "classification_confidence": "high",
        "classification_source": "ai",
        "suggested_debit_account": "Equipment",
        "suggested_credit_account": "Cash",
    }


@pytest.fixture
def classification_low():
    return {
        "expense_category": "software",
        "classification_confidence": "low",
        "classification_source": "fallback_rules",
        "suggested_debit_account": "SHOULD NOT USE THIS",
        "suggested_credit_account": "SHOULD NOT USE THIS",
    }
