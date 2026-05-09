# make/odoo.mk — Odoo 18 ERP 服務管理
#
# 首次啟動流程：
#   1. make odoo            → 啟動 PostgreSQL + Odoo 18（背景執行）
#   2. 等 ~60 秒 Odoo 初始化完成
#   3. 瀏覽器開 http://localhost:8069，建立資料庫（DB Name: odoo, admin passwd: admin）
#   4. Settings → Users → admin → API Keys → 建立 API Key
#   5. 把 API Key 填入 backend/.env 的 ODOO_API_KEY
#   6. make seed-odoo       → 植入 6 張 Vendor Bills 示範資料

.PHONY: odoo odoo-down odoo-logs odoo-reset seed-odoo

## 背景啟動 Odoo 18 + PostgreSQL（port 8069）
odoo:
	docker compose up odoo-db odoo -d

## 停止 Odoo 服務（保留資料 volume）
odoo-down:
	docker compose stop odoo odoo-db

## 即時查看 Odoo log
odoo-logs:
	docker compose logs -f odoo

## 完整重置 Odoo（刪除 volume，下次 make odoo 重新初始化）
odoo-reset:
	docker compose stop odoo odoo-db
	docker compose rm -f odoo odoo-db
	docker volume rm finance-automation_odoo-data finance-automation_odoo-db-data || true

## 植入示範 Vendor Bills（需先完成首次初始化並設定 ODOO_API_KEY）
seed-odoo:
	@echo "Waiting for Odoo to be ready..."
	@until curl -sf http://localhost:8069/web/health > /dev/null 2>&1; do \
	  printf '.'; sleep 3; \
	done
	@echo " Odoo ready."
	uv --directory backend run python scripts/seed_odoo.py
