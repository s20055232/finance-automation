# make/clean.mk — 清理

.PHONY: clean

## 清除所有自動產生的檔案（保留程式碼）
clean:
	rm -rf backend/sample_data/invoices/* backend/output/* backend/storage/* site/
	@echo "已清除發票、報表、向量資料庫、文件輸出。"
