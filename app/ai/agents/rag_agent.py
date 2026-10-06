import re
from typing import Any

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from loguru import logger

from app.ai.knowledge_core.rag_setup import RAGPipeline
from app.ai.knowledge_core.retrieval.retriever import Retriever
from app.ai.llm_client import LLMClient, normalize_llm_text
from app.ai.prompts.rag_agent_prompt import RAG_HUMAN_PROMPT, RAG_SYSTEM_PROMPT

#: Exact reply used when the retrieved context holds no answer. The chat workflow
#: turns this (and any ungrounded retrieval) into a clarifying follow-up question
#: so the assistant asks the patient instead of guessing.
RAG_NOT_FOUND_RESPONSE = "I don't have that information in my clinic knowledge base."
_NOT_FOUND = RAG_NOT_FOUND_RESPONSE

#: Below this evidence score the retrieved text is the nearest chunk, not real
#: support for the question.
EVIDENCE_FLOOR = 0.12

_STOPWORDS = {
    "about",
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
    "is",
    "me",
    "nishant",
    "of",
    "on",
    "please",
    "should",
    "tell",
    "the",
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
    "address": {"location", "located"},
    "appointment": {"booking", "book", "schedule"},
    "book": {"appointment", "booking", "schedule"},
    "contact": {"phone", "email", "number"},
    "doctor": {"specialist"},
    "fee": {"payment", "charge", "cost", "price"},
    "hours": {"open", "opening", "reception"},
    "location": {"address", "located"},
    "medicine": {"medication", "prescribe", "prescription"},
    "open": {"hours", "opening", "reception"},
    "payment": {"fee", "charge", "cost", "price"},
    "services": {"departments", "diagnostic", "consultation"},
}


class RAGAgent:
    """
    RAG Agent — lazy initialization, Gemini-ready, messages converted to dicts.
    """

    def __init__(
        self,
        docs_dir: str,
        persist_dir: str = "vector_db/faiss",
        llm_model: str | None = None,
        temperature: float | None = None,
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
                f"Page: {doc.metadata.get('page', 'NA')}\n"
                f"Chunk ID: {doc.metadata.get('chunk_id', 'NA')}\n\n"
                f"Relevance: {doc.metadata.get('relevance_score', 'NA')}\n\n"
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

    def _query_terms(self, query: str) -> set[str]:
        terms = {
            token
            for token in re.findall(r"[a-z0-9]+", query.lower())
            if len(token) > 2 and token not in _STOPWORDS
        }
        if not terms and "nishant care" in query.lower():
            terms = {"healthcare", "services", "located"}
        expanded = set(terms)
        for term in terms:
            expanded.update(_SYNONYMS.get(term, set()))
        return expanded

    def _evidence_score(self, query: str, docs: list[Document]) -> float:
        query_terms = self._query_terms(query)
        if not query_terms or not docs:
            return 0.0

        best = 0.0
        for doc in docs:
            content_terms = set(re.findall(r"[a-z0-9]+", doc.page_content.lower()))
            overlap = len(query_terms & content_terms) / max(len(query_terms), 1)
            retriever_score = float(doc.metadata.get("relevance_score") or 0.0)
            best = max(best, overlap, retriever_score)
        return best

    def _has_relevant_evidence(self, query: str, docs: list[Document]) -> bool:
        # Below the floor the retrieved text is likely just the nearest available
        # chunk, not actual evidence for the question.
        return self._evidence_score(query, docs) >= EVIDENCE_FLOOR

    def _extractive_answer(self, query: str, docs: list[Document]) -> str:
        """Best-effort clinic answer when the LLM is unavailable."""
        if not docs:
            return _NOT_FOUND

        query_terms = self._query_terms(query)
        if query_terms and not self._has_relevant_evidence(query, docs):
            return _NOT_FOUND

        sentences: list[tuple[int, str]] = []
        for doc in docs:
            text = doc.page_content.strip()
            lines = [line.strip(" ·\t") for line in text.splitlines() if line.strip(" ·\t")]
            candidates = lines + re.split(r"(?<=[.!?])\s+", text)
            for sentence in candidates:
                clean = " ".join(sentence.split())
                if not clean:
                    continue
                sentence_terms = set(re.findall(r"[a-z0-9]+", clean.lower()))
                score = len(query_terms & sentence_terms)
                if clean.endswith(":") or clean.istitle():
                    score += 1 if query_terms & sentence_terms else 0
                sentences.append((score, clean))

        scored = sorted(sentences, key=lambda item: item[0], reverse=True)
        selected = [sentence for score, sentence in scored if score > 0][:3]
        if not selected:
            selected = [doc.page_content.strip().replace("\n", " ") for doc in docs[:2] if doc.page_content.strip()]

        if not selected:
            return _NOT_FOUND
        return " ".join(selected[:3])

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

        # 1. Retrieve chunks
        try:
            docs = self.retriever.retrieve(query, top_k=top_k)
        except Exception as exc:
            logger.error(f"RAG retrieval failed: {exc}")
            return {
                "response": _NOT_FOUND,
                "chunks": [],
                "confidence": 0.0,
                "grounded": False,
            }
        if not docs:
            return {
                "response": _NOT_FOUND,
                "chunks": [],
                "confidence": 0.0,
                "grounded": False,
            }
        confidence = self._evidence_score(query, docs)
        if not self._has_relevant_evidence(query, docs):
            return {
                "response": _NOT_FOUND,
                "chunks": docs,
                "confidence": confidence,
                "grounded": False,
            }

        # 2. Format context
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
            messages_dicts[0]["content"] = f"{system_prompt.strip()}\n\n{RAG_SYSTEM_PROMPT}"

        # 5️⃣ Call LLM
        try:
            llm_response = self.llm.invoke(messages_dicts)  # list of dicts, not objects
            response_text = normalize_llm_text(llm_response).strip()
        except Exception as e:
            logger.error(f"LLM invocation failed: {e}")
            response_text = self._extractive_answer(query, docs)
        if not response_text:
            response_text = self._extractive_answer(query, docs)

        return {
            "response": response_text,
            "chunks": docs,
            "confidence": confidence,
            "grounded": True,
        }
