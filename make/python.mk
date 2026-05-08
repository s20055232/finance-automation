# make/python.mk — Python 後端相關指令

.PHONY: install install-s3 samples dev-backend demo demo-noai

install:
	uv sync

install-s3:
	uv sync --extra s3

## 產生 6 張 PDF + 1 張 CSV 範例發票
samples:
	uv run python sample_data/generate_samples.py

## 啟動 FastAPI 開發伺服器（port 8000，hot reload）
dev-backend:
	uv run uvicorn api:app --reload --port 8000

## 執行 CLI 完整流程（需 .env 設定 ANTHROPIC_API_KEY）
demo:
	uv run python demo.py

## 執行 CLI 流程，跳過 Claude API（不需 API key）
demo-noai:
	uv run python demo.py --no-ai
