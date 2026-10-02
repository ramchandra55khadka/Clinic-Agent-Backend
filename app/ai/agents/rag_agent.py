from typing import Any

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from loguru import logger

from app.ai.knowledge_core.rag_setup import RAGPipeline
from app.ai.knowledge_core.retrieval.retriever import Retriever
from app.ai.llm_client import LLMClient
from app.ai.prompts.rag_agent_prompt import RAG_HUMAN_PROMPT, RAG_SYSTEM_PROMPT


class RAGAgent:
    """
    RAG Agent — lazy initialization, Gemini-ready, messages converted to dicts.
    """

    def __init__(
        self,
        docs_dir: str,
        persist_dir: str = "vector_db/faiss",
        llm_model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
        top_k: int = 5,
    ):
        logger.info("Initializing RAG Agent (lazy mode)...")

        self.docs_dir = docs_dir
        self.persist_dir = persist_dir
        self.top_k = top_k

        self.pipeline: RAGPipeline | None = None
        self.retriever: Retriever | None = None
        self._initialized = False

        self.llm = LLMClient(model=llm_model, temperature=temperature)

        # --------------------------
        # Final Prompt Template
        # --------------------------
        self.prompt_template = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(RAG_SYSTEM_PROMPT),
            HumanMessagePromptTemplate.from_template(RAG_HUMAN_PROMPT),
        ])


        logger.info("RAG Agent instance created (lazy initialization).")

    # --------------------------------------------------------------------
    def _ensure_initialized(self):
        if self._initialized:
            return

        logger.info("Lazy initializing RAG pipeline and FAISS retriever...")
        self.pipeline = RAGPipeline(
            docs_dir=self.docs_dir,
            persist_dir=self.persist_dir,
            top_k=self.top_k,
        )
        self.retriever = self.pipeline.setup()
        self._initialized = True

        logger.info("RAG pipeline and retriever ready (loaded once).")

    # --------------------------------------------------------------------
    def _format_context(self, docs: list[Document]) -> str:
        """Format FAISS documents for the LLM context."""
        parts = []
        for doc in docs:
            parts.append(
                f"Source: {doc.metadata.get('source', 'unknown')}\n"
                f"Chunk ID: {doc.metadata.get('chunk_id', 'NA')}\n\n"
                f"{doc.page_content}\n"
                "------------------------------"
            )
        return "\n".join(parts)

    # --------------------------------------------------------------------
    def _messages_to_dicts(self, messages) -> list[dict[str, str]]:
        """
        Convert SystemMessage / HumanMessage objects to dicts for Gemini.
        """
        converted = []
        for msg in messages:
            role = "system" if msg.type == "system" else "user"
            converted.append({"role": role, "content": msg.content})
        return converted

    # --------------------------------------------------------------------
    def answer(
        self,
        query: str,
        top_k: int | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_initialized()
        top_k = top_k or self.top_k
        logger.info(f"Processing query: {query}")

        # 1️⃣ Retrieve chunks
        docs = self.retriever.retrieve(query, top_k=top_k)

        # 2️⃣ Format context
        context_text = self._format_context(docs)

        # 3️⃣ Format messages using prompt template
        messages = self.prompt_template.format_messages(
            context=context_text,
            query=query
        )

        # 4️⃣ Convert LangChain messages to dicts (Gemini-safe)
        messages_dicts = self._messages_to_dicts(messages)

        # Optional: override system prompt
        if system_prompt:
            messages_dicts[0]["content"] = system_prompt

        # 5️⃣ Call LLM
        try:
            llm_response = self.llm.invoke(messages_dicts)  # list of dicts, not objects
            response_text = getattr(llm_response, "content", str(llm_response)).strip()
        except Exception as e:
            logger.error(f"LLM invocation failed: {e}")
            response_text = "I encountered an error generating the response.LLM invocation Failed"

        return {
            "response": response_text,
            "chunks": docs
        }
