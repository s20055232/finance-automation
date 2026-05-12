"""
api.py — FastAPI server

=== Endpoints ===
  GET  /health                 — health check（Oathkeeper allow-list）
  GET  /api/odoo/status        — 確認 Odoo 連線狀態
  POST /api/odoo/sync          — 從 Odoo 拉取 Vendor Bills + 跑完整 pipeline
  POST /api/invoices/upload    — 上傳 PDF/CSV + 跑 pipeline
  GET  /api/reports            — 列出已產生的 Excel 報表
  GET  /api/reports/{filename} — 下載報表檔案

=== Auth ===
  Oathkeeper 驗證 session 後，將 X-User-ID header 注入每個 request。
  /health 列在 oathkeeper allow-list，不需要 session。
"""

import logging
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import INPUT_DIR, OUTPUT_DIR
from src import classification_cache as cache
from src.classifier import classify_invoice
from src.extractor import extract_from_file
from src.journal import generate_journal_entries
from src.models import AnomalyFlag, ClassifiedInvoice, InvoiceData, ReconciliationReport
from src.odoo_connector import ODOO_URL, fetch_vendor_bills, get_client
from src.rag_store import InvoiceRAGStore
from src.reconciler import reconcile
from src.reporter import generate_excel_report

_rag = InvoiceRAGStore()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Smart Invoice & Reconciliation Bot",
    description="AI-powered invoice processing and reconciliation",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",    # Vite dev server
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4455",   # Oathkeeper proxy
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Response models ────────────────────────────────────────────────────────────

class JournalEntryOut(BaseModel):
    account_name: str
    account_type: str
    debit_amount: float
    credit_amount: float
    description: str


class AnomalyOut(BaseModel):
    severity: str
    anomaly_type: str
    invoice_number: str
    vendor_name: str
    description: str
    amount: float | None


class InvoiceOut(BaseModel):
    invoice_number: str
    vendor_name: str
    invoice_date: str
    total_amount: float
    currency: str
    source_file: str
    expense_category: str
    expense_subcategory: str
    classification_confidence: str
    classification_source: str
    journal_entries: list[JournalEntryOut]
    anomalies: list[AnomalyOut]


class ReconciliationOut(BaseModel):
    total_invoices: int
    total_debits: float
    total_credits: float
    is_balanced: bool
    anomaly_count: int
    critical_count: int
    warning_count: int
    cache_hits: int
    ai_calls: int
    invoices: list[InvoiceOut]
    report_filename: str | None


class OdooStatusOut(BaseModel):
    connected: bool
    url: str
    message: str


# ── Pipeline helpers ───────────────────────────────────────────────────────────

def _run_pipeline(invoices: list[InvoiceData]) -> tuple[list[ClassifiedInvoice], int, int]:
    """回傳 (classified_list, cache_hits, ai_calls)。"""
    classified = []
    cache_hits = 0
    ai_calls = 0
    for invoice in invoices:
        try:
            hit = cache.get(invoice)
            if hit:
                classification = hit
                cache_hits += 1
            else:
                classification = classify_invoice(invoice)
                cache.set(invoice, classification)
                ai_calls += 1

            entries = generate_journal_entries(invoice, classification)
            classified.append(ClassifiedInvoice(
                invoice=invoice,
                expense_category=classification["expense_category"],
                expense_subcategory=classification.get("expense_subcategory", "general"),
                classification_confidence=classification["classification_confidence"],
                classification_source=classification["classification_source"],
                journal_entries=entries,
                ai_reasoning=classification.get("ai_reasoning"),
            ))
        except Exception as e:
            logger.warning("Pipeline failed for %s: %s", invoice.invoice_number, e)
    return classified, cache_hits, ai_calls


def _to_out(report: ReconciliationReport, cache_hits: int = 0, ai_calls: int = 0) -> ReconciliationOut:
    # 用 source_file 當 key，確保相同 invoice_number 的不同 invoice 不會共用 anomalies
    anomaly_map: dict[str, list[AnomalyFlag]] = {}
    for a in report.anomalies:
        key = a.source_file if a.source_file else a.invoice_number
        anomaly_map.setdefault(key, []).append(a)

    invoices_out = [
        InvoiceOut(
            invoice_number=ci.invoice.invoice_number,
            vendor_name=ci.invoice.vendor_name,
            invoice_date=ci.invoice.invoice_date,
            total_amount=ci.invoice.total_amount,
            currency=ci.invoice.currency,
            source_file=ci.invoice.source_file,
            expense_category=ci.expense_category,
            expense_subcategory=ci.expense_subcategory,
            classification_confidence=ci.classification_confidence,
            classification_source=ci.classification_source,
            journal_entries=[
                JournalEntryOut(
                    account_name=e.account_name,
                    account_type=e.account_type,
                    debit_amount=e.debit_amount,
                    credit_amount=e.credit_amount,
                    description=e.description,
                )
                for e in ci.journal_entries
            ],
            anomalies=[
                AnomalyOut(
                    severity=a.severity,
                    anomaly_type=a.anomaly_type,
                    invoice_number=a.invoice_number,
                    vendor_name=a.vendor_name,
                    description=a.description,
                    amount=a.amount,
                )
                for a in anomaly_map.get(ci.invoice.source_file, [])
            ],
        )
        for ci in report.processed_invoices
    ]

    return ReconciliationOut(
        total_invoices=len(report.processed_invoices),
        total_debits=report.total_debits,
        total_credits=report.total_credits,
        is_balanced=report.is_balanced,
        anomaly_count=len(report.anomalies),
        critical_count=sum(1 for a in report.anomalies if a.severity == "critical"),
        warning_count=sum(1 for a in report.anomalies if a.severity == "warning"),
        cache_hits=cache_hits,
        ai_calls=ai_calls,
        invoices=invoices_out,
        report_filename=None,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "finance-automation"}


@app.get("/api/odoo/status", response_model=OdooStatusOut)
async def odoo_status():
    from src.odoo_connector import ODOO_API_KEY
    if not ODOO_API_KEY:
        return OdooStatusOut(connected=False, url=ODOO_URL, message="ODOO_API_KEY not set")
    client = get_client()
    if client is None:
        return OdooStatusOut(connected=False, url=ODOO_URL, message="Cannot connect to Odoo")
    return OdooStatusOut(connected=True, url=ODOO_URL, message=f"Connected (uid={client.uid})")


@app.post("/api/odoo/sync", response_model=ReconciliationOut)
async def odoo_sync(x_user_id: str = Header(default="anonymous")):
    logger.info("Odoo sync triggered by user=%s", x_user_id)
    client = get_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Odoo not available. Check ODOO_API_KEY and Odoo is running.",
        )

    invoices = fetch_vendor_bills(client)
    if not invoices:
        raise HTTPException(status_code=404, detail="No posted vendor bills found in Odoo.")

    classified, hits, calls = _run_pipeline(invoices)
    if not classified:
        raise HTTPException(status_code=422, detail="Pipeline produced no results.")

    logger.info("Sync done: %d cached, %d AI calls", hits, calls)
    _rag.index_batch(classified)
    report = reconcile(classified)
    report_path = generate_excel_report(report)

    out = _to_out(report, cache_hits=hits, ai_calls=calls)
    out.report_filename = report_path.name
    return out


@app.post("/api/invoices/upload", response_model=ReconciliationOut)
async def upload_invoice(
    file: UploadFile = File(...),
    x_user_id: str = Header(default="anonymous"),
):
    allowed = {".pdf", ".csv", ".xlsx"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(allowed))}",
        )

    logger.info("Invoice upload by user=%s: %s", x_user_id, file.filename)
    dest = INPUT_DIR / (file.filename or "upload.pdf")

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        invoice = extract_from_file(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Cannot extract invoice data: {e}")

    classified, hits, calls = _run_pipeline([invoice])
    if not classified:
        raise HTTPException(status_code=422, detail="Pipeline produced no results.")

    _rag.index_batch(classified)
    report = reconcile(classified)
    report_path = generate_excel_report(report)

    out = _to_out(report, cache_hits=hits, ai_calls=calls)
    out.report_filename = report_path.name
    return out


class QueryIn(BaseModel):
    question: str

@app.post("/api/query")
async def query_invoices(body: QueryIn):
    stats = _rag.get_stats()
    if stats["total_indexed"] == 0:
        raise HTTPException(status_code=404, detail="No invoices indexed yet. Run a sync first.")
    answer = _rag.query(body.question)
    return {"answer": answer, "indexed": stats["total_indexed"]}


@app.get("/api/reports")
async def list_reports():
    files = sorted(OUTPUT_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "modified": f.stat().st_mtime,
        }
        for f in files
    ]


@app.get("/api/reports/{filename}")
async def download_report(filename: str):
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
