# Smart Invoice & Reconciliation Bot

> AI + RPA 智能化發票處理與自動對帳系統

這個系統展示了會計工作的未來：**從「執行者」到「流程設計者」**。
傳統上需要人工一張一張看的發票，現在由 AI 自動判讀、分類、對帳，
會計人員只需要關注系統無法處理的例外情況。

---

## 四階段自動化流程

```
PDF / CSV 發票
      │
      ▼  Phase 1：資料擷取（OCR + RPA）
  extractor.py  ←  pdfplumber 解析 PDF 文字與表格
      │
      ▼  Phase 2：AI 分類 + 借貸分錄
  classifier.py ←  Claude API（費用類別判斷）
  journal.py    ←  自動產生借方 / 貸方分錄
      │
      ▼  Phase 3：對帳與異常偵測
  reconciler.py ←  試算表（總借 = 總貸）、重複發票、異常金額
      │
      ▼  Phase 4：報表 + 警報
  reporter.py   ←  Excel 報表（Trial Balance + 損益表）
                ←  Email 自動警報（偵測到異常時觸發）
      │
      ▼  歸檔 + 語意索引
  storage.py    ←  原始 PDF 存入 Object Storage（Local / S3）
  rag_store.py  ←  ChromaDB 向量索引（支援自然語言查詢）
```

---

## 技術棧

| 層次 | 技術 | 說明 |
|------|------|------|
| AI 分類 | Claude API (`claude-sonnet-4-6`) | Prompt Caching 降低成本 |
| PDF 解析 | pdfplumber + regex | 無需重量級 OCR 引擎 |
| 語意搜尋 | ChromaDB + sentence-transformers | 本地向量資料庫，零外部依賴 |
| API Server | FastAPI + Uvicorn | 自動產生 OpenAPI 文件 |
| 前端 | Vue 3 + Vite | 組件化，Hot Module Replacement |
| 認證 | Ory Kratos + Oathkeeper | Zero Trust IAP，身份與應用解耦 |
| 報表輸出 | openpyxl | Excel 多工作表，含條件格式 |
| 環境管理 | uv + pyproject.toml | 比 pip 快 10-100x |

---

## 快速開始

```bash
make install       # 安裝 Python 依賴
make samples       # 產生 6 張範例發票（PDF + CSV）
make auth          # 啟動認證服務（需要 Docker）
make dev           # 同時啟動 API + 前端
```

詳細步驟請見 [快速開始指南](guide/quickstart.md)。
