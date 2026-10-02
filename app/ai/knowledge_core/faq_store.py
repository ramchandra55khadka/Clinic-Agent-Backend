from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from loguru import logger

from app.ai.knowledge_core.embeddings import EmbeddingsStore
from app.core.config import settings


class FAQItem:
    def __init__(
        self,
        faq_id: str,
        category: str,
        question: str,
        answer: str,
    ) -> None:
        self.id = faq_id
        self.category = category
        self.question = question
        self.answer = answer

    def to_document(self, index: int) -> Document:
        return Document(
            page_content=self.question,
            metadata={
                "id": f"faq:{self.id}",
                "faq_id": self.id,
                "category": self.category,
                "question": self.question,
                "answer": self.answer,
                "source": "faq",
                "chunk_id": index,
            },
        )


class FAQStore:
    def __init__(
        self,
        faq_path: str | None = None,
        persist_directory: str | None = None,
        similarity_threshold: float | None = None,
        max_results: int | None = None,
    ) -> None:
        self.faq_path = faq_path or settings.faq_path
        self.persist_directory = persist_directory or str(
            Path(settings.persist_dir).with_name("faiss_faq")
        )
        self.similarity_threshold = similarity_threshold or settings.faq_similarity_threshold
        self.max_results = max_results or settings.faq_max_results

        self.embeddings_store = EmbeddingsStore(persist_directory=self.persist_directory)
        self._faiss: FAISS | None = None
        self._faqs: list[FAQItem] = []

        self._load_faqs()
        self._ensure_index()

    def _load_faqs(self) -> None:
        path = Path(self.faq_path)
        if not path.exists():
            logger.warning(f"FAQ file not found: {path}")
            self._faqs = []
            return

        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            logger.error(f"Failed to read FAQ file {path}: {exc}")
            self._faqs = []
            return

        faqs = data.get("faqs", [])
        self._faqs = [
            FAQItem(
                faq_id=item.get("id") or f"faq_{idx:03d}",
                category=item.get("category") or "general",
                question=item.get("question") or "",
                answer=item.get("answer") or "",
            )
            for idx, item in enumerate(faqs)
        ]
        logger.info(f"Loaded {len(self._faqs)} FAQ entries from {path}")

    def _ensure_index(self) -> None:
        if not self._faqs:
            self._faiss = None
            return

        documents = [faq.to_document(index=i) for i, faq in enumerate(self._faqs)]
        self._faiss = self.embeddings_store.build_or_load(documents=documents)
        logger.info("FAQ FAISS index ready")

    def search(self, query: str, k: int | None = None) -> list[dict[str, Any]]:
        if not self._faiss or not query.strip():
            return []

        k = k or self.max_results
        try:
            # The index is built with metric_type=INNER_PRODUCT, so FAISS returns
            # a distance-like score where LOWER is better. Convert to a cosine
            # similarity (higher is better) to match the configured threshold.
            results = self._faiss.similarity_search_with_score(query, k=k)
        except Exception as exc:
            logger.error(f"FAQ search failed: {exc}")
            return []

        matches: list[dict[str, Any]] = []
        for doc, raw_score in results:
            similarity = 1.0 - float(raw_score)
            if similarity < self.similarity_threshold:
                continue
            metadata = doc.metadata or {}
            matches.append(
                {
                    "faq_id": metadata.get("faq_id"),
                    "category": metadata.get("category"),
                    "question": metadata.get("question"),
                    "answer": metadata.get("answer"),
                    "score": round(similarity, 4),
                    "source": "faq",
                }
            )
        return matches
