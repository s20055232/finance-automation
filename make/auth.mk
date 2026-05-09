# make/auth.mk — Ory Zero Trust 認證服務（Docker Compose）

.PHONY: gen-secrets auth auth-down auth-logs mail

## 自動產生 Kratos secret 並寫入 .env（若尚未設定）
gen-secrets:
	uv run python3 scripts/gen_secrets.py

## 背景啟動認證服務（Kratos + Oathkeeper + Mailpit）
auth: gen-secrets
	docker compose up -d kratos-migrate kratos oathkeeper mailpit
	@echo ""
	@echo "認證服務啟動中..."
	@echo "  Oathkeeper proxy : http://127.0.0.1:4455"
	@echo "  Kratos public    : http://127.0.0.1:4433"
	@echo "  Mailpit UI       : http://127.0.0.1:8025"
	@echo ""

## 停止並移除所有認證容器
auth-down:
	docker compose down

## 建立 demo 帳號（demo@example.com / demo1234）供本地開發登入
seed-user:
	@curl -sf -X POST http://127.0.0.1:4434/admin/identities \
	  -H "Content-Type: application/json" \
	  -d '{"schema_id":"default","traits":{"email":"demo@example.com"},"credentials":{"password":{"config":{"password":"demo1234"}}}}' \
	  | python3 -m json.tool \
	  && echo "\n✓ 帳號建立：demo@example.com / demo1234" \
	  || echo "（帳號可能已存在，請直接登入）"

## 即時查看認證服務 log（Ctrl+C 離開）
auth-logs:
	docker compose logs -f kratos oathkeeper

## 在瀏覽器開啟 Mailpit（查看 Kratos 寄出的驗證信）
mail:
	open http://127.0.0.1:8025
