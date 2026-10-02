from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import GOOGLE_API_KEY


class LLMClient:
    def __init__(self,model: str = "gemini-2.5-flash",temperature: float=0.2):
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not set. Add it to .env before using LLM endpoints.")
        self.llm=ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
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

        response=self.llm.invoke(messages)
        return response.content
