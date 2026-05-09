# make/docs.mk — MkDocs 說明文件

.PHONY: docs-install docs docs-build docs-deploy

## 安裝 MkDocs 相關套件
docs-install:
	uv sync --group docs

## 本地預覽文件（port 8001，hot reload）
## port 8001 避免與 FastAPI（8000）衝突
docs:
	uv run --group docs mkdocs serve --dev-addr 0.0.0.0:8001

## 打包靜態文件（輸出到 site/）
docs-build:
	uv run --group docs mkdocs build

## 部署到 GitHub Pages（推送到 gh-pages branch）
docs-deploy:
	uv run --group docs mkdocs gh-deploy --force --clean
