# make/python.mk — Python 後端相關指令

.PHONY: install install-s3 samples dev-backend backend backend-down backend-logs test

install:
	uv --directory backend sync

install-s3:
	uv --directory backend sync --extra s3

## 產生 6 張 PDF + 1 張 CSV 範例發票
samples:
	uv --directory backend run python sample_data/generate_samples.py

## 啟動 FastAPI 開發伺服器（port 8000，hot reload，不走 Docker）
dev-backend:
	uv --directory backend run uvicorn api:app --reload --port 8000

## 建置並背景啟動 FastAPI backend（Docker，含 Oathkeeper 整合）
backend:
	docker compose up backend -d --build

## 停止 backend container
backend-down:
	docker compose stop backend

## 即時查看 backend log
backend-logs:
	docker compose logs -f backend

## 執行單元測試
test:
	uv --directory backend run --group dev pytest tests -v
