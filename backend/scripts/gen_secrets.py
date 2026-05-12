"""
gen_secrets.py — 自動產生 Kratos secret 並寫入 .env

若 .env 已有對應的 key 則跳過，不覆蓋已有的值。
"""
import secrets
from pathlib import Path

ENV_FILE = Path(__file__).parent.parent.parent / ".env"  # project root（docker-compose 讀這裡）

REQUIRED = [
    "KRATOS_SECRET_COOKIE",
    "KRATOS_SECRET_CIPHER",
]

content = ENV_FILE.read_text() if ENV_FILE.exists() else ""
added = []

for key in REQUIRED:
    if key not in content:
        value = secrets.token_hex(16)   # 32 字元 hex
        content = content.rstrip() + f"\n{key}={value}\n"
        added.append(key)

if added:
    ENV_FILE.write_text(content)
    print(f"Added to .env: {', '.join(added)}")
else:
    print("Kratos secrets already set in .env")
