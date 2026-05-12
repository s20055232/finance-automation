.PHONY: tunnel tunnel-stop

tunnel: ## 啟動 Cloudflare Named Tunnel（allenlaiproject.com → :4455）
	cloudflared tunnel --config cloudflared/config.yml run

tunnel-stop: ## 停止 Cloudflare Named Tunnel
	pkill cloudflared || true
