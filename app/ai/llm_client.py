import threading
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import (
    GOOGLE_AI_MODEL,
    GOOGLE_API_KEY,
    LLM_REQUEST_DELAY_SECONDS,
    LLM_TEMPERATURE,
)

_llm_request_lock = threading.Lock()
_last_llm_request_at = 0.0


def _wait_for_llm_slot() -> None:
    """Space out LLM calls to avoid local free-tier burst limits."""
    global _last_llm_request_at

    if LLM_REQUEST_DELAY_SECONDS <= 0:
        return

    with _llm_request_lock:
        now = time.monotonic()
        wait_seconds = LLM_REQUEST_DELAY_SECONDS - (now - _last_llm_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_llm_request_at = time.monotonic()


def normalize_llm_text(value: Any) -> str:
    """Return plain text from LangChain/Gemini responses and content blocks."""
    content = getattr(value, "content", value)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


class LLMClient:
    def __init__(self, model: str | None = None, temperature: float | None = None):
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not set. Add it to .env before using LLM endpoints.")
        self.llm=ChatGoogleGenerativeAI(
            model=model or GOOGLE_AI_MODEL,
            temperature=LLM_TEMPERATURE if temperature is None else temperature,
            api_key=GOOGLE_API_KEY
        )


    def invoke(self, prompt: str | list[dict[str, Any]], system_prompt: str | None = None) -> str:
        """
        Generate text from a user prompt, optionally including a system prompt.

        Args:
            prompt (str): The main user prompt.
            system_prompt (str | None): Optional system instruction for context.

        Returns:
            str: Generated text from Gemini 2.5 Flash.
        """
        messages = []
        if isinstance(prompt, list):
            for item in prompt:
                role = item.get("role", "user")
                content = item.get("content", "")
                if role == "system":
                    messages.append(SystemMessage(content=content))
                else:
                    messages.append(HumanMessage(content=content))
        else:
            if system_prompt:
                messages.append(SystemMessage(content=system_prompt))
            messages.append(HumanMessage(content=prompt))

        _wait_for_llm_slot()
        response=self.llm.invoke(messages)
        return normalize_llm_text(response)
