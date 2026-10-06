import re
from pathlib import Path

from langchain_core.documents import Document
from loguru import logger

from app.ai.knowledge_core.embeddings import EmbeddingsStore
from app.core.config import settings

_STOPWORDS = {
    "about",
    "after",
    "again",
    "are",
    "can",
    "care",
    "clinic",
    "does",
    "for",
    "from",
    "give",
    "have",
    "how",
    "into",
    "is",
    "me",
    "nishant",
    "of",
    "on",
    "please",
    "should",
    "tell",
    "that",
    "the",
    "their",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "you",
    "your",
}

_SYNONYMS = {
    "address": {"location", "located", "where"},
    "appointment": {"booking", "book", "schedule", "visit"},
    "book": {"appointment", "booking", "schedule"},
    "cancel": {"cancellation", "cancelled"},
    "contact": {"phone", "email", "number"},
    "doctor": {"specialist", "physician"},
    "emergency": {"urgent", "life-threatening"},
    "fee": {"payment", "cost", "charge", "price"},
    "hours": {"open", "opening", "reception"},
    "location": {"address", "located", "where"},
    "medicine": {"medication", "prescribe", "prescription"},
    "mission": {"aims", "purpose"},
    "open": {"hours", "opening", "reception"},
    "payment": {"fee", "cost", "charge", "price"},
    "reschedule": {"change", "move"},
    "services": {"departments", "diagnostic", "consultation"},
    "vision": {"future", "goal"},
}


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    }


def _expanded_terms(text: str) -> set[str]:
    terms = _terms(text)
    if not terms and "nishant care" in text.lower():
        terms = {"healthcare", "services", "located"}
    expanded = set(terms)
    for term in terms:
        expanded.update(_SYNONYMS.get(term, set()))
    return expanded


class Retriever:
    """Sementic retriever. auto loads existing FAISS index on init -never crashes."""
    def __init__(
        self,
        persist_directory: str = "vector_db/faiss",
        store: EmbeddingsStore | None = None,
        cache_size: int = 128,
    ):
        self.store = store or EmbeddingsStore(persist_directory=persist_directory)
        self._cache_size = cache_size
        self._query_cache: dict[tuple[str, int], list[Document]] = {}

        #Safe load: check if FAISS index exists
        index_file=Path(self.store.persist_directory) / "index.faiss"
        if self.store.db is not None:
            logger.success("Retriever ready - FAISS index already loaded")
        elif index_file.exists():
            try:
                self.store.build_or_load(documents=None) #just load
                logger.success("Retriever ready - FAISS index loaded")
            except Exception as e:
                logger.error(f"Failded to load FAISS index: {e}")
                self.store.db=None
        else:
            logger.warning("No FAISS index found. Call ingest() first or upload PDFs.")
            self.store.db=None
    
    def retrieve(self, query: str, top_k: int = 6) -> list[Document]:
        """Retrieve top-k relevant chunks as Documents."""
        if not self.store.db:
            raise ValueError(
                "Vector store not loaded. Upload and process PDFs first."
            )
        cache_key = (" ".join(query.lower().split()), top_k)
        if cache_key in self._query_cache:
            logger.debug(f"Retrieved {len(self._query_cache[cache_key])} cached chunks for query: '{query[:70]}...'")
            return list(self._query_cache[cache_key])

        candidate_k = max(top_k, settings.retrieval_candidates)
        docs = self.store.query(query, k=candidate_k)
        docs = self._dedupe(docs)
        docs = self._rerank(query, docs)[:top_k]
        self._remember(cache_key, docs)
        logger.info(f"Retrieved {len(docs)} chunks for query: '{query[:70]}...'")
        return docs

    def _dedupe(self, docs: list[Document]) -> list[Document]:
        seen: set[str] = set()
        unique: list[Document] = []
        for doc in docs:
            key = str(
                doc.metadata.get("id")
                or f"{doc.metadata.get('source')}:{doc.metadata.get('page')}:{doc.metadata.get('chunk_id')}"
                or doc.page_content[:160]
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(doc)
        return unique

    def _rerank(self, query: str, docs: list[Document]) -> list[Document]:
        query_terms = _expanded_terms(query)
        if not query_terms:
            return docs

        query_phrases = [
            phrase
            for phrase in re.findall(r"[a-z0-9][a-z0-9 ]{4,}", query.lower())
            if len(phrase.split()) >= 2
        ]

        scored: list[tuple[float, int, Document]] = []
        for index, doc in enumerate(docs):
            content = doc.page_content.lower()
            doc_terms = _terms(content)
            if not doc_terms:
                lexical = 0.0
            else:
                overlap = query_terms & doc_terms
                lexical = len(overlap) / max(len(query_terms), 1)
                if overlap:
                    lexical += min(len(overlap), 4) * 0.08

            phrase_score = sum(0.15 for phrase in query_phrases if phrase in content)
            heading_bonus = 0.0
            first_line = content.splitlines()[0] if content.splitlines() else ""
            if query_terms & _terms(first_line):
                heading_bonus = 0.12

            # Earlier FAISS results still matter; lexical reranking should refine,
            # not erase, semantic retrieval.
            semantic_prior = 1.0 / (index + 1)
            score = lexical + phrase_score + heading_bonus + (semantic_prior * 0.05)
            doc.metadata["relevance_score"] = round(score, 4)
            scored.append((score, -index, doc))

        min_score = settings.retrieval_min_score
        ranked = [doc for score, _index, doc in sorted(scored, reverse=True) if score >= min_score]
        return ranked or [doc for _score, _index, doc in sorted(scored, reverse=True)]

    def _remember(self, cache_key: tuple[str, int], docs: list[Document]) -> None:
        if self._cache_size <= 0:
            return
        if len(self._query_cache) >= self._cache_size:
            oldest_key = next(iter(self._query_cache))
            self._query_cache.pop(oldest_key, None)
        self._query_cache[cache_key] = list(docs)

    def retrieve_with_score(self, query: str, top_k: int = 6):
        """
        Retrieve top-k relevant chunks with similarity scores.
        Returns: list of tuples (Document, score)
        """
        if not self.store.db:
            raise ValueError("Vector store not loaded.")
        if not hasattr(self.store.db, "similarity_search_with_score"):
            raise AttributeError("FAISS DB does not support similarity_search_with_score.")
        return self.store.db.similarity_search_with_score(query, k=top_k)

    def is_ready(self) -> bool:
        """Check if retriever has a loaded FAISS index."""
        return self.store.db is not None
