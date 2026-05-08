"""
storage.py — 原始發票檔案的物件儲存

=== 設計概念 ===
RPA 機器人處理完每一張發票後，原始檔（PDF / CSV）應該歸檔備存。
這等同於傳統會計「紙本發票要存檔」的數位版本。

本模組使用「策略模式」：
  - StorageBackend（抽象介面）定義合約
  - LocalStorageBackend   實作本地資料夾版本（預設，demo 用）
  - S3StorageBackend      實作 AWS S3 版本（生產用，stub）
  - get_storage()         工廠函式，根據 STORAGE_BACKEND 環境變數自動選擇

切換只需改一行 .env：
    STORAGE_BACKEND=local   # 預設
    STORAGE_BACKEND=s3      # 生產環境

儲存 key 格式（兩種 backend 相同）：
    invoices/2024/01/INV-2024-001_acme_tech.pdf
"""

import os
import shutil
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path


# ── 抽象介面（合約）──────────────────────────────────────────────────────────

class StorageBackend(ABC):
    """
    所有 Object Storage 實作都必須遵守這個介面。
    只要符合這三個方法，任何 backend 都可以無縫替換。
    """

    @abstractmethod
    def store(self, source_path: Path, invoice_date: str | None = None) -> str:
        """
        將原始發票檔存入 storage，回傳 storage key。

        Args:
            source_path:  原始檔路徑（PDF 或 CSV）
            invoice_date: 發票日期（YYYY-MM-DD），用於資料夾分類；
                          未提供則用今天。
        Returns:
            storage_key: 例如 "invoices/2024/01/INV-2024-001.pdf"
        """

    @abstractmethod
    def retrieve(self, storage_key: str) -> Path:
        """
        根據 storage_key 取得檔案的本地 Path。
        S3 實作下需先下載到暫存位置再回傳。
        """

    @abstractmethod
    def list_keys(self, year: int | None = None, month: int | None = None) -> list[str]:
        """
        列出已存入的 key 清單，可依年/月篩選。

        範例：
            list_keys(2024, 1)  → 2024 年 1 月所有發票
            list_keys(2024)     → 2024 年全年
            list_keys()         → 所有發票
        """


# ── Local Backend ─────────────────────────────────────────────────────────────

class LocalStorageBackend(StorageBackend):
    """
    本地資料夾實作。按 invoices/YYYY/MM/ 結構自動分類。
    不需要任何外部服務，適合 demo 與開發環境。
    """

    def __init__(self, root: Path | None = None) -> None:
        default_root = Path(__file__).parent.parent / "storage"
        self._root = root or default_root
        self._root.mkdir(parents=True, exist_ok=True)

    def store(self, source_path: Path, invoice_date: str | None = None) -> str:
        parsed = _parse_date(invoice_date)
        dest_dir = self._root / "invoices" / str(parsed.year) / f"{parsed.month:02d}"
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_path = self._resolve_unique(dest_dir, source_path.name)
        shutil.copy2(source_path, dest_path)
        return dest_path.relative_to(self._root).as_posix()

    def retrieve(self, storage_key: str) -> Path:
        path = self._root / storage_key
        if not path.exists():
            raise FileNotFoundError(f"Invoice not found: {storage_key}")
        return path

    def list_keys(self, year: int | None = None, month: int | None = None) -> list[str]:
        base = self._root / "invoices"
        if not base.exists():
            return []

        if year and month:
            search_dir = base / str(year) / f"{month:02d}"
        elif year:
            search_dir = base / str(year)
        else:
            search_dir = base

        if not search_dir.exists():
            return []

        return [
            p.relative_to(self._root).as_posix()
            for p in sorted(search_dir.rglob("*"))
            if p.is_file() and p.suffix.lower() in {".pdf", ".csv", ".xlsx"}
        ]

    @staticmethod
    def _resolve_unique(directory: Path, filename: str) -> Path:
        """若同名檔案已存在，自動加版本號（_v2, _v3...）。"""
        stem, suffix = Path(filename).stem, Path(filename).suffix
        candidate = directory / filename
        for version in range(2, 100):
            if not candidate.exists():
                return candidate
            candidate = directory / f"{stem}_v{version}{suffix}"
        return candidate


# ── S3 Backend（stub，供日後啟用）────────────────────────────────────────────

class S3StorageBackend(StorageBackend):
    """
    AWS S3 實作。
    啟用方式：
        1. pip install boto3
        2. .env 加入：
               AWS_BUCKET=your-bucket
               AWS_REGION=ap-northeast-1
               AWS_ACCESS_KEY_ID=...
               AWS_SECRET_ACCESS_KEY=...
        3. STORAGE_BACKEND=s3

    切換後呼叫端（demo.py、main.py）不需要改任何程式碼，
    因為介面與 LocalStorageBackend 完全相同。
    """

    def __init__(self) -> None:
        try:
            import boto3  # noqa: F401
        except ImportError:
            raise ImportError("S3 backend requires boto3. Run: uv pip install boto3")

        import boto3
        self._bucket = os.environ["AWS_BUCKET"]
        self._s3 = boto3.client(
            "s3",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        self._tmp_dir = Path("/tmp/finance_bot_cache")
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

    def store(self, source_path: Path, invoice_date: str | None = None) -> str:
        parsed = _parse_date(invoice_date)
        key = f"invoices/{parsed.year}/{parsed.month:02d}/{source_path.name}"
        self._s3.upload_file(str(source_path), self._bucket, key)
        return key

    def retrieve(self, storage_key: str) -> Path:
        local_path = self._tmp_dir / Path(storage_key).name
        self._s3.download_file(self._bucket, storage_key, str(local_path))
        return local_path

    def list_keys(self, year: int | None = None, month: int | None = None) -> list[str]:
        prefix = "invoices/"
        if year:
            prefix += f"{year}/"
        if year and month:
            prefix += f"{month:02d}/"

        paginator = self._s3.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return sorted(keys)


# ── 工廠函式（對外唯一入口）──────────────────────────────────────────────────

_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """
    根據環境變數回傳對應的 StorageBackend 單例。
    呼叫端只需要：

        from src.storage import get_storage
        storage = get_storage()
        key = storage.store(path, invoice_date="2024-01-15")
    """
    global _instance
    if _instance is None:
        backend = os.getenv("STORAGE_BACKEND", "local").lower()
        if backend == "s3":
            _instance = S3StorageBackend()
        else:
            _instance = LocalStorageBackend()
    return _instance


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _parse_date(date_str: str | None) -> date:
    """解析日期字串；無法解析則回傳今天。"""
    if not date_str:
        return date.today()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return date.today()
