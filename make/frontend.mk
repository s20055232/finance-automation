# make/frontend.mk — Vue 3 + Vite 前端相關指令

.PHONY: install-frontend dev-frontend build-frontend dev

## 安裝 npm 依賴
install-frontend:
	cd frontend && npm install

## 啟動 Vite dev server（port 5173，hot reload）
dev-frontend:
	cd frontend && npm run dev

## 打包前端靜態檔（輸出到 frontend/dist/）
build-frontend:
	cd frontend && npm run build

## 同時啟動 FastAPI + Vite（需安裝 concurrently）
dev:
	npx concurrently \
	  "uv --directory backend run uvicorn api:app --reload --port 8000" \
	  "cd frontend && npm run dev" \
	  --names "backend,frontend" \
	  --prefix-colors "cyan,magenta"
