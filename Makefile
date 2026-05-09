# Smart Invoice & Reconciliation Bot
#
# ── 快速開始 ──────────────────────────────────────────────────────────────────
#   1. make install && make install-frontend
#   2. make samples          → 產生測試發票
#   3. make auth             → 啟動認證服務（需要 Docker）
#   4. make dev              → 同時啟動 FastAPI + Vite
#   5. 瀏覽器 → http://127.0.0.1:4455
#
# ── 完整指令請看各 .mk 檔案 ──────────────────────────────────────────────────
#   make/python.mk    → install, samples, dev-backend, demo
#   make/frontend.mk  → install-frontend, dev-frontend, build-frontend, dev
#   make/auth.mk      → gen-secrets, auth, auth-down, auth-logs, mail, seed-user
#   make/odoo.mk      → odoo, odoo-down, odoo-logs, odoo-reset, seed-odoo
#   make/docs.mk      → docs-install, docs, docs-build
#   make/clean.mk     → clean

include make/python.mk
include make/frontend.mk
include make/auth.mk
include make/odoo.mk
include make/docs.mk
include make/clean.mk
