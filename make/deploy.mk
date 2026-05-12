.PHONY: deploy

deploy: ## 拉取最新程式碼並重啟所有服務
	git pull origin main
	docker compose up -d --build
	@echo "部署完成。確認狀態：docker compose ps"
