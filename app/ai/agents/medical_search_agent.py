"""General medical question agent backed by keyless DuckDuckGo search.

DuckDuckGo provides web-search results through the `ddgs` package without a
search API key. Results are explicitly filtered to trusted medical domains. If a
Gemini API key is configured, Gemini summarizes those grounded results;
otherwise, the agent builds a concise answer from retrieved snippets.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS
from loguru import logger

from app.ai.llm_client import LLMClient, normalize_llm_text
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
SOURCE_PRIORITY = {
    "medlineplus.gov": 0,
    "mayoclinic.org": 1,
    "nhs.uk": 2,
    "cdc.gov": 3,
    "who.int": 4,
    "wikipedia.org": 5,
}


class MedicalSearchAgent:
    def __init__(self):
        self._llm: LLMClient | None = None

    def _get_llm(self) -> LLMClient | None:
        if not settings.google_api_key:
            return None
        if self._llm is None:
            self._llm = LLMClient()
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

    def _source_priority(self, link: str) -> int:
        hostname = (urlparse(link).hostname or "").removeprefix("www.")
        for domain, priority in SOURCE_PRIORITY.items():
            if hostname == domain or hostname.endswith(f".{domain}"):
                return priority
        return len(SOURCE_PRIORITY)

    def _clean_snippet(self, snippet: str) -> str:
        text = re.sub(r"\[[^\]]*\]", "", snippet)
        text = re.sub(r"\s+", " ", text).strip(" .")
        text = re.sub(r"\s+([,.;:])", r"\1", text)
        return text

    def _snippet_sentences(self, snippet: str) -> list[str]:
        cleaned = self._clean_snippet(snippet)
        if not cleaned:
            return []
        return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", cleaned) if sentence.strip()]

    def _definition_sentences(self, query: str, results: list[dict[str, str]]) -> list[str]:
        query_terms = {term for term in re.findall(r"[a-zA-Z]{4,}", query.lower()) if term not in {"what", "medical"}}
        definition_patterns = (
            " is ",
            " are ",
            " refers to ",
            " means ",
            " studies ",
            " involves ",
            " includes ",
        )
        noisy_phrases = ("cell culture vials", "university of", "research complex")

        candidates: list[tuple[int, int, str]] = []
        for source_index, item in enumerate(sorted(results, key=lambda result: self._source_priority(result["link"]))):
            for sentence in self._snippet_sentences(item.get("snippet", "")):
                sentence_lower = sentence.lower()
                if any(phrase in sentence_lower for phrase in noisy_phrases):
                    continue
                has_query_term = not query_terms or any(term in sentence_lower for term in query_terms)
                has_definition = any(pattern in sentence_lower for pattern in definition_patterns)
                if not has_query_term and not has_definition:
                    continue
                score = 0
                if has_query_term:
                    score -= 2
                if has_definition:
                    score -= 2
                if len(sentence) > 220:
                    score += 2
                candidates.append((score, source_index, sentence))

        selected: list[str] = []
        seen: set[str] = set()
        for _score, _source_index, sentence in sorted(candidates):
            key = sentence.lower()
            if key in seen:
                continue
            selected.append(sentence.rstrip(".") + ".")
            seen.add(key)
            if len(selected) >= 3:
                break
        return selected

    def _source_answer(self, query: str, results: list[dict[str, str]]) -> str:
        sentences = self._definition_sentences(query, results)
        if not sentences:
            sentences = [
                sentence.rstrip(".") + "."
                for item in sorted(results, key=lambda result: self._source_priority(result["link"]))
                for sentence in self._snippet_sentences(item.get("snippet", ""))
                if sentence
            ][:2]
        if not sentences:
            return "I found relevant medical sources, but they did not include enough preview text to answer clearly."

        answer = " ".join(sentences)
        if len(answer) > 700:
            answer = answer[:700].rsplit(" ", 1)[0].rstrip(" .") + "."

        source_titles = [item["title"].strip() for item in results[:2] if item.get("title", "").strip()]
        if source_titles:
            answer = f"{answer}\n\nSources checked: {', '.join(source_titles)}."

        lowered = query.lower()
        if lowered.startswith(("who is", "what is", "what are")):
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
                response = normalize_llm_text(llm.invoke(messages))
            except Exception as exc:  # pragma: no cover - provider/quota dependent
                logger.error("Medical web summarization failed: {} ({})", type(exc).__name__, exc)
                response = self._source_answer(query, results)

        return {"response": normalize_llm_text(response).strip(), "data": {"sources": results, "provider": "duckduckgo", "search_available": True}}
