# Smart Invoice & Reconciliation Bot

> AI + RPA automated invoice processing and reconciliation system

This project demonstrates the future of accounting work: **from executor to process designer**.
Invoices that once required manual review are now automatically parsed, classified, and reconciled by AI.
Accountants focus only on exceptions that the system cannot handle.

---

## Four-Phase Automation Pipeline

```
PDF / CSV Invoices
      │
      ▼  Phase 1: Data Extraction (OCR + RPA)
  extractor.py  ←  pdfplumber parses PDF text and tables
      │
      ▼  Phase 2: AI Classification + Journal Entries
  classifier.py ←  Claude API (expense category detection)
  journal.py    ←  Auto-generate debit / credit entries
      │
      ▼  Phase 3: Reconciliation & Anomaly Detection
  reconciler.py ←  Trial balance (debits = credits), duplicate invoices, large amounts
      │
      ▼  Phase 4: Reports + Alerts
  reporter.py   ←  Excel report (Trial Balance + Income Statement)
                ←  Automated email alert on anomaly detection
      │
      ▼  Archive + Semantic Index
  storage.py    ←  Store original PDF in Object Storage (Local / S3)
  rag_store.py  ←  ChromaDB vector index (natural language queries)
```

---

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| AI Classification | Claude API (`claude-sonnet-4-6`) | Prompt Caching for cost efficiency |
| PDF Parsing | pdfplumber + regex | No heavy OCR engine required |
| Semantic Search | ChromaDB + sentence-transformers | Local vector DB, zero external deps |
| API Server | FastAPI + Uvicorn | Auto-generates OpenAPI docs |
| Frontend | Vue 3 + Vite | Component-based, Hot Module Replacement |
| Authentication | Ory Kratos + Oathkeeper | Zero Trust IAP, identity decoupled from app |
| Report Output | openpyxl | Multi-sheet Excel with conditional formatting |
| Environment | uv + pyproject.toml | 10-100x faster than pip |

---

## Quick Start

```bash
make install       # Install Python dependencies
make samples       # Generate 6 sample invoices (PDF + CSV)
make auth          # Start auth services (requires Docker)
make dev           # Start API + frontend simultaneously
```

See the [Quick Start Guide](guide/quickstart.md) for detailed steps.
