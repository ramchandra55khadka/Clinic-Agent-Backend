"""General medical question agent backed by keyless DuckDuckGo search.

DuckDuckGo provides web-search results through the `ddgs` package without a
search API key. Results are explicitly filtered to trusted medical domains. If a
Gemini API key is configured, Gemini summarizes those grounded results;
otherwise, the agent builds a concise answer from retrieved snippets.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS
from loguru import logger

from app.ai.llm_client import LLMClient
from app.ai.prompts.medical_search_agent_prompt import MEDICAL_SEARCH_SYSTEM_PROMPT
from app.core.config import settings

TRUSTED_DOMAINS = {
    "mayoclinic.org",
    "nhs.uk",
    "cdc.gov",
    "who.int",
    "medlineplus.gov",
    "wikipedia.org",
}
TRUSTED_MEDICAL_SITES = " OR ".join(f"site:{domain}" for domain in sorted(TRUSTED_DOMAINS))


class MedicalSearchAgent:
    def __init__(self):
        self._llm: LLMClient | None = None

    def _get_llm(self) -> LLMClient | None:
        if not settings.google_api_key:
            return None
        if self._llm is None:
            self._llm = LLMClient(model="gemini-2.5-flash", temperature=0.2)
        return self._llm

    def _is_trusted_medical_source(self, url: str) -> bool:
        hostname = (urlparse(url).hostname or "").lower()
        return any(hostname == domain or hostname.endswith(f".{domain}") for domain in TRUSTED_DOMAINS)

    def _duckduckgo_search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        search_query = f"{query} {TRUSTED_MEDICAL_SITES}"
        try:
            raw_results = DDGS().text(search_query, max_results=max_results * 3)
        except Exception as exc:  # pragma: no cover - provider/network dependent
            logger.error("DuckDuckGo search failed through ddgs: {} ({})", type(exc).__name__, exc)
            return []

        results: list[dict[str, str]] = []
        for item in raw_results:
            link = str(item.get("href") or item.get("url") or "")
            if not link or not self._is_trusted_medical_source(link):
                continue
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("body") or item.get("snippet") or "").strip()
            if title:
                results.append({"title": title, "link": link, "snippet": snippet})
            if len(results) >= max_results:
                break

        if not results:
            logger.error("DuckDuckGo returned no trusted medical results for query: {}", query)
        return results


    def _source_answer(self, query: str, results: list[dict[str, str]]) -> str:
        snippets = [item.get("snippet", "").strip() for item in results if item.get("snippet", "").strip()]
        if not snippets:
            return "I found relevant medical sources, but they did not include enough preview text to answer clearly."

        answer = " ".join(snippets[:3])
        answer = " ".join(answer.split())
        if len(answer) > 650:
            answer = answer[:650].rsplit(" ", 1)[0] + "."

        lowered = query.lower()
        if lowered.startswith("who is"):
            return answer
        if lowered.startswith(("what is", "what are")):
            return answer
        return answer + " This is general educational information, not a diagnosis or treatment plan."

    def answer(self, query: str, system_prompt: str | None = None) -> dict[str, Any]:
        results = self._duckduckgo_search(query)
        if not results:
            return {
                "response": (
                    "DuckDuckGo web search did not return trusted medical sources right now. "
                    "Please check backend internet/DNS access and try again."
                ),
                "data": {"sources": [], "provider": "duckduckgo", "search_available": False},
            }

        context = "\n".join(
            f"[{index}] {item['title']}\n{item['snippet']}\n{item['link']}"
            for index, item in enumerate(results, start=1)
        )
        prompt = MEDICAL_SEARCH_SYSTEM_PROMPT.format(query=query, context=context)

        llm = self._get_llm()
        if llm is None:
            response = self._source_answer(query, results)
        else:
            messages = (
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]
                if system_prompt
                else prompt
            )
            try:
                response = llm.invoke(messages)
            except Exception as exc:  # pragma: no cover - provider/quota dependent
                logger.error("Medical web summarization failed: {} ({})", type(exc).__name__, exc)
                response = self._source_answer(query, results)

        return {"response": response.strip(), "data": {"sources": results, "provider": "duckduckgo", "search_available": True}}
