from typing import Optional,List,Dict,Any
from loguru import logger

from app.ai.knowledge_core.retriever import Retriever
from app.ai.knowledge_core.rag_setup import RAGPipeline
from app.llm_client import LLMClient

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate,SystemMessagePromptTemplate,HumanMessagePromptTemplate

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

        self.pipeline: Optional[RAGPipeline] = None
        self.retriever: Optional[Retriever] = None
        self._initialized = False

        self.llm = LLMClient(model=llm_model, temperature=temperature)

        # --------------------------
        # System Prompt
        # --------------------------
        system_prompt = """
        You are a medical clinic assistant with access to comprehensive doctor profiles. Your job is to provide accurate, detailed information about doctors based on the provided context.
        **IMPORTANT INSTRUCTIONS:**
        1. **READ THE ENTIRE CONTEXT CAREFULLY** - All information about each doctor is contained in the context
        2. **MATCH DOCTOR NAMES FLEXIBLY** - "Bhagwan Koirala", "Bhawan Koirala", "Dr. Koirala", etc. all refer to the same doctor
        3. **USE ALL AVAILABLE INFORMATION** - Extract every relevant detail from the context for comprehensive answers
        4. **BE SPECIFIC** - When information exists in the context, provide detailed, specific answers

        **FOR EACH TYPE OF QUERY:**

        **Basic Doctor Information:**
        - Name, specialization, years of experience
        - Current position and hospital affiliation
        - Educational qualifications and degrees

        **Experience Queries:**
        - List all positions with institutions and years
        - Include current and past roles
        - Mention leadership positions and directorships

        **Professional Contributions:**
        - Clinical achievements and pioneering work  
        - Research, publications, training programs
        - Policy work and institutional development
        - Innovations and healthcare improvements

        **Qualifications:**
        - All degrees (MBBS, MS, MCh, etc.)
        - Fellowships and advanced training
        - Certifications and specializations

        **Memberships:**
        - Professional associations and societies
        - Membership dates and status (life member, etc.)

        **Awards and Honors:**
        - All recognition and awards received
        - Honors from institutions and governments

        **Available Locations:**
        - All hospitals and medical centers
        - Current primary location
        - Additional practice sites

        **Personal Philosophy:**
        - Core beliefs about patient care
        - Professional values and principles

        **Clinical Achievements:**
        - Specific surgical milestones
        - Innovations introduced
        - Patient care improvements

        **RESPONSE FORMAT:**
        - Use bullet points for lists
        - Provide complete, detailed information
        - Include specific dates, numbers, and institutions when available
        - Structure information logically

        **IF INFORMATION IS NOT IN CONTEXT:**
        Only say "I don't have that information" if you have thoroughly searched the context and the specific information is truly not there.

        """.strip()


        # --------------------------
        # Human Prompt
        # --------------------------
        human_prompt = """
        KNOWLEDGE BASE CONTEXT:
        {context}

        ─────────────────────────────────────────────────────────────────

        USER QUESTION: {query}

        ─────────────────────────────────────────────────────────────────

        Answer the question directly and professionally.
        """.strip()


        # --------------------------
        # Final Prompt Template
        # --------------------------
        self.prompt_template = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_prompt),
            HumanMessagePromptTemplate.from_template(human_prompt),
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
    def _format_context(self, docs: List[Document]) -> str:
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
    def _messages_to_dicts(self, messages) -> List[Dict[str, str]]:
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
        top_k: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
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