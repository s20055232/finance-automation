"""
classification_cache.py — 發票分類結果快取

=== 設計 ===
  key  = sha256(invoice_number | vendor_name | total_amount)[:16]
  值   = classify_invoice() 回傳的 dict（JSON 序列化）
  存放 = storage/classification_cache.json（持久化，重啟不失效）

=== 快取命中條件 ===
  同一張發票（相同 invoice_number + vendor + 金額）第二次跑 sync 時，
  直接回傳快取結果，不再呼叫 LLM。

  金額包含在 key 裡：若 Odoo 更正了金額，key 不同 → 自動重新分類。

=== 清除快取 ===
  DELETE /api/cache  — 清空全部
  rm backend/storage/classification_cache.json  — 手動清除
"""

import hashlib
import json
import logging
from pathlib import Path

from src.models import InvoiceData

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent.parent / "storage" / "classification_cache.json"


def _key(invoice: InvoiceData) -> str:
    raw = f"{invoice.invoice_number}|{invoice.vendor_name}|{invoice.total_amount:.2f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _load() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def get(invoice: InvoiceData) -> dict | None:
    """快取命中回傳分類 dict，未命中回傳 None。"""
    data = _load()
    hit = data.get(_key(invoice))
    if hit:
        logger.info("Cache hit: %s (%s)", invoice.invoice_number, invoice.vendor_name)
    return hit


def set(invoice: InvoiceData, result: dict) -> None:
    """將分類結果寫入快取（upsert）。"""
    data = _load()
    data[_key(invoice)] = result
    _save(data)


def stats() -> dict:
    """回傳快取統計。"""
    data = _load()
    return {"cached_invoices": len(data), "cache_path": str(CACHE_PATH)}


def clear() -> int:
    """清空快取，回傳被清除的筆數。"""
    data = _load()
    count = len(data)
    _save({})
    logger.info("Classification cache cleared (%d entries)", count)
    return count
