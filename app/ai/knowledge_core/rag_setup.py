import os
import shutil

from loguru import logger

from app.ai.knowledge_core.embeddings import EmbeddingsStore
from app.ai.knowledge_core.loader import PDFLoader
from app.ai.knowledge_core.retrieval.retriever import Retriever
from app.core.config import settings


class RAGPipeline:
    """
    Setup RAG pipeline: PDFs -> embeddings -> FAISS -> Retriever
    """

    def __init__(self, docs_dir: str, persist_dir: str = "vector_db/faiss", top_k: int = 5):
        if not os.path.isdir(docs_dir):
            logger.error(f"Documents directory does not exist: {docs_dir}")
            raise ValueError(f"Documents directory does not exist: {docs_dir}")

        if not isinstance(top_k, int) or top_k <= 0:
            logger.error(f"Invalid top_k value: {top_k}")
            raise ValueError("top_k must be a positive integer")

        self.docs_dir = docs_dir
        self.persist_dir = persist_dir
        self.top_k = top_k

        self.retriever: Retriever | None = None
        self.vectorstore: EmbeddingsStore | None = None

        logger.info(f"RAGSetup initialized: docs_dir={docs_dir}, persist_dir={persist_dir}, top_k={top_k}")

    def _pdf_mtime(self) -> float:
        newest = 0.0
        for root, _dirs, files in os.walk(self.docs_dir):
            for file_name in files:
                if file_name.lower().endswith(".pdf"):
                    newest = max(newest, os.path.getmtime(os.path.join(root, file_name)))
        return newest

    def setup(self) -> Retriever:
        """
        Load PDFs, build FAISS vectorstore, and return a ready Retriever.
        Uses memory-safe streaming loader for large PDFs.
        """
        try:
            store = EmbeddingsStore(persist_directory=self.persist_dir)

            index_path = os.path.join(self.persist_dir, "index.faiss")
            index_exists = os.path.exists(index_path)
            if index_exists and settings.rag_rebuild_index:
                logger.info("RAG_REBUILD_INDEX enabled -> rebuilding FAISS index from PDFs")
                shutil.rmtree(self.persist_dir, ignore_errors=True)
                index_exists = False
            elif index_exists and self._pdf_mtime() > os.path.getmtime(index_path):
                logger.info("Clinic PDFs changed after FAISS index was built -> rebuilding index")
                shutil.rmtree(self.persist_dir, ignore_errors=True)
                index_exists = False

            if index_exists:
                # Existing FAISS → skip PDF loading
                logger.info("Existing FAISS index found → loading without reprocessing PDFs")
                self.vectorstore = store.build_or_load(documents=None)
            else:
                # No FAISS → load PDFs and build
                logger.info("No FAISS index found → loading and chunking PDFs")

                loader = PDFLoader(
                    pdf_dir=self.docs_dir,
                    stream_mode=True  # enable memory-safe streaming
                )
                docs = loader.load_documents()
                self.vectorstore = store.build_or_load(documents=docs if docs else [])

            # Initialize retriever with the loaded store so FAISS is not loaded twice.
            self.retriever = Retriever(persist_directory=self.persist_dir, store=store)
            logger.info("Retriever ready to use")
            return self.retriever

        except Exception as e:
            logger.error(f"RAG setup failed: {e}")
            raise RuntimeError(f"RAG setup failed: {e}") from e
