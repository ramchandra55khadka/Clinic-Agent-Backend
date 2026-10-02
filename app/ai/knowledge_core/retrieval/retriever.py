from pathlib import Path

from langchain_core.documents import Document
from loguru import logger

from app.ai.knowledge_core.embeddings import EmbeddingsStore


class Retriever:
    """Sementic retriever. auto loads existing FAISS index on init -never crashes."""
    def __init__(self,persist_directory:str="vector_db/faiss"):
        self.store=EmbeddingsStore(persist_directory=persist_directory)

        #Safe load: check if FAISS index exists
        index_file=Path(self.store.persist_directory) / "index.faiss"
        if index_file.exists():
            try:
                self.store.build_or_load(documents=None) #just load
                logger.success("Retriever ready - FAISS index loaded")
            except Exception as e:
                logger.error(f"Failded to load FAISS index: {e}")
                self.store.db=None
        else:
            logger.warning("No FAISS index found. Call ingest() first or upload PDFs.")
            self.store.db=None
    
    def retrieve(self, query: str, top_k: int = 6) -> list[Document]:
        """Retrieve top-k relevant chunks as Documents."""
        if not self.store.db:
            raise ValueError(
                "Vector store not loaded. Upload and process PDFs first."
            )
        docs = self.store.query(query, k=top_k)
        logger.info(f"Retrieved {len(docs)} chunks for query: '{query[:70]}...'")
        return docs

    def retrieve_with_score(self, query: str, top_k: int = 6):
        """
        Retrieve top-k relevant chunks with similarity scores.
        Returns: list of tuples (Document, score)
        """
        if not self.store.db:
            raise ValueError("Vector store not loaded.")
        if not hasattr(self.store.db, "similarity_search_with_score"):
            raise AttributeError("FAISS DB does not support similarity_search_with_score.")
        return self.store.db.similarity_search_with_score(query, k=top_k)

    def is_ready(self) -> bool:
        """Check if retriever has a loaded FAISS index."""
        return self.store.db is not None