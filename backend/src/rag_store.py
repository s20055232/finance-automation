"""
rag_store.py — 發票語意索引與自然語言查詢（RAG）

=== 什麼是 RAG？===
RAG（Retrieval-Augmented Generation）= 「先搜尋，再生成」。

傳統方式：問 AI 問題 → AI 從訓練資料回答（可能過時、沒有你公司的資料）
RAG 方式：
  1. 先把公司資料（發票、合約、報表）轉成向量存入向量資料庫
  2. 收到問題時，先搜出最相關的資料片段
  3. 把搜出的資料 + 問題一起丟給 Claude
  4. Claude 根據真實資料回答 → 準確、可追溯

本模組流程：
  存入：InvoiceData → 轉成文字描述 → ChromaDB 向量化儲存
  查詢：自然語言問題 → ChromaDB 語意搜尋 → 結果交給 Claude 彙整 → 回答

使用範例：
    store = InvoiceRAGStore()
    store.index_invoice(classified_invoice)

    answer = store.query("這個月花了多少廣告費？")
    print(answer)
"""

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

# OrbStack injects IPv6 CIDR entries (e.g. fd07:b51a:cc66:f0::/64) into no_proxy.
# httpx (used by chromadb for model download) can't parse them as URL patterns and raises
# InvalidURL. Strip any entry containing ':' (IPv6) before chromadb is imported.
for _k in ('no_proxy', 'NO_PROXY'):
    _v = os.environ.get(_k, '')
    if _v:
        os.environ[_k] = ','.join(e for e in _v.split(',') if ':' not in e)

import chromadb
from chromadb.config import Settings

if TYPE_CHECKING:
    from src.models import ClassifiedInvoice

# ChromaDB 向量資料庫存放位置（本地持久化）
CHROMA_DIR = Path(__file__).parent.parent / "storage" / "chroma_db"

# 一次查詢最多取回幾筆相關發票
DEFAULT_TOP_K = 5


class InvoiceRAGStore:
    """
    發票向量索引。
    負責：存入發票 → 語意搜尋 → 呼叫 Claude 彙整結果。

    設計重點：
    - ChromaDB 使用預設的本地 embedding（sentence-transformers）
      → demo 不需要額外的 embedding API
    - 每張發票轉成一段「自然語言摘要」再存入
      → 讓向量搜尋可以理解語意，不只是關鍵字比對
    - Claude 負責最後的彙整，把搜出的多筆資料整理成完整回答
    """

    def __init__(self, persist_dir: Path | None = None) -> None:
        self._dir = persist_dir or CHROMA_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=str(self._dir),
            settings=Settings(anonymized_telemetry=False),
        )
        # collection = 向量資料庫裡的一張「資料表」
        self._collection = self._client.get_or_create_collection(
            name="invoices",
            metadata={"hnsw:space": "cosine"},   # 用餘弦相似度比較向量
        )

    # ── 存入 ─────────────────────────────────────────────────────────────────

    def index_invoice(self, classified: "ClassifiedInvoice") -> None:
        """
        將一張已分類的發票存入向量資料庫。

        做法：
          1. 把發票重要欄位轉成一段自然語言文字（document）
          2. ChromaDB 自動把這段文字轉成向量（embedding）
          3. 同時把結構化的 metadata 也存進去，供篩選用
        """
        inv = classified.invoice
        document = _invoice_to_text(classified)

        # metadata 只能存純量型別（str / int / float / bool）
        metadata = {
            "invoice_number":   inv.invoice_number,
            "vendor_name":      inv.vendor_name,
            "invoice_date":     inv.invoice_date,
            "total_amount":     inv.total_amount,
            "currency":         inv.currency,
            "expense_category": classified.expense_category,
            "confidence":       classified.classification_confidence,
            "source_file":      inv.source_file,
            "storage_key":      classified.storage_key or "",
            "indexed_at":       datetime.now().isoformat(),
        }

        # id 用 invoice_number + vendor 組合，確保同張發票重複 index 時不會重複
        doc_id = f"{inv.invoice_number}_{inv.vendor_name}".replace(" ", "_").lower()

        self._collection.upsert(
            ids=[doc_id],
            documents=[document],
            metadatas=[metadata],
        )

    def index_batch(self, classified_invoices: list["ClassifiedInvoice"]) -> int:
        """批次存入，回傳成功筆數。"""
        count = 0
        for inv in classified_invoices:
            try:
                self.index_invoice(inv)
                count += 1
            except Exception as e:
                print(f"  [RAG] 索引失敗 {inv.invoice.invoice_number}: {e}")
        return count

    # ── 查詢 ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        語意搜尋：根據自然語言查詢找出最相關的發票。

        Args:
            query:   自然語言問題，例如「一月份的廣告費」
            top_k:   最多回傳幾筆
            filters: ChromaDB where 條件，例如 {"expense_category": "marketing"}

        Returns:
            list of dict，每筆包含 metadata + distance（相似度距離，越小越相似）
        """
        kwargs: dict = {"query_texts": [query], "n_results": min(top_k, self._count())}
        if filters:
            kwargs["where"] = filters

        results = self._collection.query(**kwargs)

        hits = []
        for i in range(len(results["ids"][0])):
            hits.append({
                "id":       results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        return hits

    def query(
        self,
        question: str,
        top_k: int = DEFAULT_TOP_K,
        filters: dict | None = None,
    ) -> str:
        """
        自然語言查詢：搜出相關發票後交給 Claude 彙整成完整回答。

        Args:
            question: 使用者問題，例如「上個月水電費總共多少？」
            top_k:    搜尋幾筆相關發票作為參考
            filters:  可選的精確篩選，例如 {"expense_category": "utilities"}

        Returns:
            Claude 的完整文字回答
        """
        hits = self.search(question, top_k=top_k, filters=filters)

        if not hits:
            return "目前資料庫中沒有相關發票資料。請先執行 demo.py 建立索引。"

        return _ask_llm(question, hits)

    def get_stats(self) -> dict:
        """回傳資料庫基本統計。"""
        return {
            "total_indexed": self._count(),
            "collection":    self._collection.name,
            "persist_dir":   str(self._dir),
        }

    def _count(self) -> int:
        return self._collection.count()


# ── 內部工具函式 ──────────────────────────────────────────────────────────────

def _invoice_to_text(classified: "ClassifiedInvoice") -> str:
    """
    把發票轉成一段自然語言摘要，讓向量搜尋理解語意。

    為什麼不直接存結構化資料？
    向量模型是為語言設計的，自然語言描述的語意搜尋效果
    比純欄位值（"marketing", 1200.00）好很多。
    """
    inv = classified.invoice
    lines_text = ", ".join(
        f"{item.description} x{item.quantity} ${item.amount:.2f}"
        for item in inv.line_items
    ) or "（無明細）"

    return (
        f"Invoice {inv.invoice_number} from vendor {inv.vendor_name}, "
        f"dated {inv.invoice_date}, "
        f"total {inv.currency} {inv.total_amount:,.2f}. "
        f"Expense category: {classified.expense_category}. "
        f"Line items: {lines_text}. "
        f"Classification reasoning: {classified.ai_reasoning or 'keyword rules'}."
    )


def _ask_llm(question: str, hits: list[dict]) -> str:
    """把搜尋結果交給 LLM 彙整成回答（Ollama → Gemini）。"""
    context_text = "\n".join(
        f"[Invoice {i}] {hit['document']} (relevance: {1 - hit['distance']:.0%})"
        for i, hit in enumerate(hits, 1)
    )
    system_prompt = (
        "You are a professional financial assistant. "
        "The user will ask questions about company invoices. "
        "Answer based solely on the invoice data provided below. "
        "Be precise and concise, citing specific invoice numbers and amounts. "
        "If the data is insufficient to answer, clearly state what information is missing."
    )
    user_message = f"Relevant invoice data:\n\n{context_text}\n\nQuestion: {question}"

    ollama_model = os.getenv("OLLAMA_MODEL", "")

    if ollama_model:
        from openai import OpenAI
        client = OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama",
        )
        resp = client.chat.completions.create(
            model=ollama_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.3,
            max_tokens=1024,
            stream=False,
        )
        return resp.choices[0].message.content or ""

    else:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
        resp = client.models.generate_content(
            model=os.getenv("AI_MODEL", "gemini-2.5-flash"),
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1024,
                temperature=0.3,
            ),
        )
        return resp.text or ""
