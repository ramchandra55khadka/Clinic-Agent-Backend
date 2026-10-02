"""FAQ agent — semantic match over the curated ``faq.json``.

The clinic's own FAQ is the cheapest and most accurate source for questions about
hours, location, payment, services and policy. This agent runs *before* document
RAG: a strong FAQ match answers directly, and anything weaker falls through to the
clinic PDF pipeline so nothing is lost.

Retrieval is embedding-based via the same FastEmbed model the FAISS RAG index uses,
so there is no extra model to provision.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.ai.knowledge_core.faq_store import FAQStore
from app.ai.llm_client import LLMClient
from app.ai.prompts.faq_agent_prompt import FAQ_SYSTEM_PROMPT


class FAQAgent:
    def __init__(
        self,
        faq_path: str | None = None,
        llm_model: str = "gemini-2.5-flash",
        temperature: float = 0.0,
    ) -> None:
        logger.info("Initializing FAQ Agent (lazy mode)...")

        self._store: FAQStore | None = None
        self._faq_path = faq_path
        self.llm = LLMClient(model=llm_model, temperature=temperature)

    def _get_store(self) -> FAQStore:
        if self._store is None:
            self._store = FAQStore(faq_path=self._faq_path)
        return self._store

    def _compose(self, question: str, match: dict[str, Any], system_prompt: str | None = None) -> str:
        """Let the LLM phrase the matched answer, falling back to it verbatim."""
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
            response = self.llm.invoke(messages)
            text = getattr(response, "content", str(response)).strip()
        except Exception as exc:
            logger.error(f"FAQ LLM phrasing failed: {exc}")
            return match["answer"]

        return text or match["answer"]

    def answer(self, query: str, system_prompt: str | None = None) -> dict[str, Any]:
        """Return the best FAQ answer, or ``matched: False`` to fall through to RAG."""
        store = self._get_store()
        matches = store.search(query, k=1)

        if not matches:
            return {"matched": False, "response": "", "faq": None}

        best = matches[0]
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
