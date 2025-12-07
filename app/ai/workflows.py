from typing import List,TypedDict,Optional
from langgraph.graph import StateGraph,END
from loguru import logger
from app.ai.agents.qa_agent import RAGAgent
from app.schemas import QueryRequest,QueryResponse
from langchain_core.documents import Document

# --------------------------------------------------------------------
# Define workflow state
class RAGState(TypedDict, total=False):
    """State used in LangGraph workflow."""
    query: str
    top_k: int
    system_prompt: Optional[str]
    agent: Optional[RAGAgent]
    chunks: Optional[List[Document]]
    response: Optional[str]


# --------------------------------------------------------------------
# Node 1: Initialize RAG agent lazily
def initialize_agent(state: RAGState) -> dict:
    """Create RAGAgent only once."""
    if state.get("agent") is None:
        logger.info("Lazy initializing RAG agent...")
        agent = RAGAgent(
            docs_dir="docs",
            persist_dir="vector_db/faiss",
            llm_model="gemini-2.5-flash",
            temperature=0.3,
            top_k=state.get("top_k", 5),
        )
        return {"agent": agent}
    return {}  # agent already exists

# --------------------------------------------------------------------
# Node 2: Retrieve answer
def retrieve_answer(state: RAGState) -> dict:
    """Retrieve top-K chunks and generate response via RAGAgent."""
    agent = state.get("agent")
    if not agent:
        raise RuntimeError("RAG agent not initialized.")

    query = state["query"]
    top_k = state.get("top_k", 5)
    system_prompt = state.get("system_prompt")

    logger.info(f"Retrieving top-{top_k} chunks for query: {query}")
    result = agent.answer(
        query=query,
        top_k=top_k,
        system_prompt=system_prompt,
    )

    return {
        "chunks": result["chunks"],
        "response": result["response"],
    }



# --------------------------------------------------------------------
# Build workflow graph
workflow = StateGraph(RAGState)

workflow.add_node("initialize_agent", initialize_agent)
workflow.add_node("retrieve_answer", retrieve_answer)

# Entry point: first initialize agent, then retrieve
workflow.set_entry_point("initialize_agent")
workflow.add_edge("initialize_agent", "retrieve_answer")
workflow.add_edge("retrieve_answer", END)

# Compile workflow app
rag_app = workflow.compile()

# --------------------------------------------------------------------
# FastAPI helper function
def run_rag(request: QueryRequest) -> QueryResponse:
    """Run LangGraph RAG workflow from API request."""
    inputs: RAGState = {
        "query": request.query,
        "top_k": request.top_k or 6,
        "system_prompt": request.system_prompt,
    }

    # Invoke LangGraph workflow
    result = rag_app.invoke(inputs)

    # Convert Document objects to dicts
    chunks = [
        {
            "content": doc.page_content,
            "source": doc.metadata.get("source"),
            "page": doc.metadata.get("page"),
            "chunk_id": doc.metadata.get("chunk_id"),
        }
        for doc in result.get("chunks", [])
    ]

    return QueryResponse(
        response=result.get("response", ""),
        chunks=chunks,
    )