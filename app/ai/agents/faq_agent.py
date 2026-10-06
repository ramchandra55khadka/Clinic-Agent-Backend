"""FAQ agent — semantic match over the curated ``faq.json``.

The clinic's own FAQ is the cheapest and most accurate source for questions about
hours, location, payment, services and policy. This agent runs *before* document
RAG: a strong FAQ match answers directly, and anything weaker falls through to the
clinic PDF pipeline so nothing is lost.

Retrieval is embedding-based via the same FastEmbed model the FAISS RAG index uses,
so there is no extra model to provision.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.ai.knowledge_core.faq_store import FAQItem, FAQStore
from app.ai.llm_client import LLMClient, normalize_llm_text
from app.ai.prompts.faq_agent_prompt import FAQ_SYSTEM_PROMPT
from app.core.config import settings


class FAQAgent:
    _STOPWORDS = {
        "a",
        "an",
        "and",
        "about",
        "are",
        "can",
        "care",
        "do",
        "does",
        "for",
        "give",
        "how",
        "i",
        "is",
        "me",
        "nishant",
        "of",
        "the",
        "tell",
        "to",
        "what",
        "when",
        "where",
        "you",
        "your",
    }

    def __init__(
        self,
        faq_path: str | None = None,
        llm_model: str | None = None,
        temperature: float | None = None,
    ) -> None:
        logger.info("Initializing FAQ Agent (lazy mode)...")

        self._store: FAQStore | None = None
        self._faq_path = faq_path
        self._llm_model = llm_model
        self._temperature = temperature
        self.llm: LLMClient | None = None

    def _get_store(self) -> FAQStore:
        if self._store is None:
            self._store = FAQStore(faq_path=self._faq_path)
        return self._store

    def _get_llm(self) -> LLMClient | None:
        """Create Gemini only when a matched FAQ actually needs phrasing."""
        if self.llm is not None:
            return self.llm
        if not settings.google_api_key:
            return None
        try:
            self.llm = LLMClient(model=self._llm_model, temperature=self._temperature)
        except Exception as exc:  # pragma: no cover - provider/config dependent
            logger.error(f"FAQ LLM initialization failed: {exc}")
            return None
        return self.llm

    def _compose(self, question: str, match: dict[str, Any], system_prompt: str | None = None) -> str:
        """Let the LLM phrase the matched answer, falling back to it verbatim."""
        llm = self._get_llm()
        if llm is None:
            return match["answer"]

        preamble = f"{system_prompt}\n\n" if system_prompt else ""
        messages = [
            {"role": "system", "content": preamble + FAQ_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"MATCHED FAQ QUESTION: {match['question']}\n\n"
                    f"APPROVED ANSWER: {match['answer']}\n\n"
                    f"PATIENT ASKED: {question}"
                ),
            },
        ]
        try:
            response = llm.invoke(messages)
            text = normalize_llm_text(response).strip()
        except Exception as exc:
            logger.error(f"FAQ LLM phrasing failed: {exc}")
            return match["answer"]

        return text or match["answer"]

    @classmethod
    def _important_terms(cls, text: str) -> set[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        terms: set[str] = set()
        for token in tokens:
            if token in cls._STOPWORDS or len(token) < 3:
                continue
            if token.endswith("ing") and len(token) > 5:
                token = token[:-3]
            elif token.endswith("ed") and len(token) > 4:
                token = token[:-2]
            elif token.endswith("s") and len(token) > 4:
                token = token[:-1]
            terms.add(token)
        return terms

    def _is_relevant_match(self, query: str, match: dict[str, Any]) -> bool:
        """Reject embedding-near but semantically wrong FAQ matches.

        Clinic-name-only similarity is common: "Mission of Nishant Care" can sit
        near "How can I contact Nishant Care?" because both mention the clinic.
        Require at least one meaningful shared term between the user's question
        and the FAQ question/category before treating a FAQ hit as authoritative.
        """
        query_terms = self._important_terms(query)
        faq_terms = self._important_terms(
            f"{match.get('question', '')} {match.get('category', '')}"
        )
        return bool(query_terms and faq_terms and query_terms & faq_terms)

    def _lexical_match(self, query: str, faqs) -> dict[str, Any] | None:
        """Prefer direct term matches before consulting the persisted vector index."""
        query_terms = self._important_terms(query)
        if not query_terms:
            return None

        candidates: list[tuple[int, FAQItem]] = []
        for faq in faqs:
            faq_terms = self._important_terms(f"{faq.question} {faq.category}")
            overlap = query_terms & faq_terms
            if len(overlap) >= 2:
                candidates.append((len(overlap), faq))

        if not candidates:
            return None

        _score, faq = sorted(candidates, key=lambda item: (item[0], len(item[1].question)), reverse=True)[0]
        return {
            "faq_id": faq.id,
            "category": faq.category,
            "question": faq.question,
            "answer": faq.answer,
            "score": 1.0,
            "source": "faq",
        }

    def answer(self, query: str, system_prompt: str | None = None) -> dict[str, Any]:
        """Return the best FAQ answer, or ``matched: False`` to fall through to RAG."""
        store = self._get_store()
        lexical_match = self._lexical_match(query, store._faqs)
        if lexical_match:
            response = self._compose(query, lexical_match, system_prompt)
            return {
                "matched": True,
                "response": response,
                "faq": {
                    "id": lexical_match["faq_id"],
                    "category": lexical_match["category"],
                    "question": lexical_match["question"],
                    "score": lexical_match["score"],
                },
            }

        matches = store.search(query, k=3)

        if not matches:
            return {"matched": False, "response": "", "faq": None}

        best = next((match for match in matches if self._is_relevant_match(query, match)), None)
        if best is None:
            return {"matched": False, "response": "", "faq": None}

        response = self._compose(query, best, system_prompt)

        return {
            "matched": True,
            "response": response,
            "faq": {
                "id": best["faq_id"],
                "category": best["category"],
                "question": best["question"],
                "score": best["score"],
            },
        }
