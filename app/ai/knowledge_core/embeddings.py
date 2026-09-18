import os
from pathlib import Path

from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from loguru import logger


class EmbeddingsStore:
    """
    Persistent FAISS vector store with FastEmbeded.
    
    Features:
    - Builds FAISS index from documents
    - Loads existing FAISS index if available
    - Adds new documents safely without duplicates
    - Saves index to disk
    """

    def __init__(self, persist_directory: str = "vector_db/faiss"):
        self.persist_directory = persist_directory
        self.embeddings = FastEmbedEmbeddings(
            model_name="BAAI/bge-small-en-v1.5"
        )
        self.db: FAISS | None = None

    def build_or_load(self, documents: list[Document] | None = None) -> FAISS:
        """
        Load existing FAISS index or build a new one from provided documents.
        If new documents are provided, adds them safely without duplicates.
        """
        os.makedirs(self.persist_directory, exist_ok=True)
        index_file = Path(self.persist_directory) / "index.faiss"

        # Assign unique IDs to each document
        if documents:
            for i, doc in enumerate(documents):
                doc.metadata["id"] = f"{doc.metadata.get('file_path','unknown')}:{doc.metadata.get('chunk_id', i)}"

        # Case 1: Existing FAISS index
        if index_file.exists():
            logger.info(f"Loading existing FAISS index from {self.persist_directory}")
            self.db = FAISS.load_local(
                folder_path=self.persist_directory,
                embeddings=self.embeddings,
                allow_dangerous_deserialization=True
            )

            # Add new documents if provided
            if documents:
                existing_ids = set(self.db.docstore._dict.keys())
                new_docs = [d for d in documents if d.metadata["id"] not in existing_ids]
                if new_docs:
                    logger.info(f"Adding {len(new_docs)} new document chunks")
                    self.db.add_documents(
                        new_docs,
                        ids=[d.metadata["id"] for d in new_docs]
                    )
                    self.db.save_local(self.persist_directory)
                else:
                    logger.info("No new documents to add")
        # Case 2: No existing index → build new
        elif documents:
            logger.info(f"Creating new FAISS index at {self.persist_directory}")
            self.db = FAISS.from_documents(
                documents=documents,
                embedding=self.embeddings
            )
            self.db.save_local(self.persist_directory)
            logger.info(f"Indexed {len(documents)} document chunks")
        else:
            raise ValueError(
                "No existing FAISS index found and no documents provided to build from."
            )

        return self.db

    def query(self, text: str, k: int = 5) -> list[Document]:
        """
        Perform semantic search and return top-k relevant document chunks.
        """
        if not self.db:
            raise ValueError("FAISS index not loaded or built yet")
        return self.db.similarity_search(text, k=k)