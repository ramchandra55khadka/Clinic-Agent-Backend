import gc
import os

import fitz  #PyMuPDF
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from app.core.config import CHUNK_OVERLAP, CHUNK_SIZE


class PDFLoader:
    """
    Memory-safe PDF loader with optional streaming for large files.
    """

    def __init__(
        self,
        pdf_dir: str,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
        batch_pages: int = 30,
        stream_mode: bool = False,
    ):
        self.pdf_dir = os.path.abspath(pdf_dir)
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)
        self.batch_pages = int(batch_pages)
        self.stream_mode = stream_mode

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ".", " "]
        )

        logger.debug(f"PDFLoader initialized: {self.pdf_dir}, stream={self.stream_mode}")

    def _discover_pdfs(self, root: str) -> list[str]:
        """Every ``*.pdf`` under ``root``, including nested subfolders."""
        found: list[str] = []
        for dir_path, _dir_names, file_names in os.walk(root):
            found.extend(
                os.path.join(dir_path, file_name)
                for file_name in file_names
                if file_name.lower().endswith(".pdf")
            )
        return found

    def load_documents(self) -> list[Document]:
        if not os.path.isdir(self.pdf_dir):
            raise FileNotFoundError(f"Directory missing: {self.pdf_dir}")

        pdf_files = sorted(self._discover_pdfs(self.pdf_dir))
        if not pdf_files:
            raise FileNotFoundError(f"No PDFs found under {self.pdf_dir}.")

        all_docs = []

        for file_path in pdf_files:
            # Relative-to-root, extension-less id: stays unique when two
            # subfolders each hold a same-named PDF.
            source_id = os.path.splitext(os.path.relpath(file_path, self.pdf_dir))[0]
            file_name = os.path.basename(file_path)
            pages: list[Document] = []

            try:
                if not self.stream_mode:
                    # Normal mode: load entire PDF at once
                    doc = fitz.open(file_path)
                    for i in range(doc.page_count):
                        text = doc[i].get_text("text")
                        if text.strip():
                            pages.append(Document(page_content=text, metadata={"source": source_id, "page": i}))
                    doc.close()
                else:
                    # Streaming mode: load PDF in batches
                    doc = fitz.open(file_path)
                    total_pages = doc.page_count

                    for start in range(0, total_pages, self.batch_pages):
                        end = min(start + self.batch_pages, total_pages)
                        for i in range(start, end):
                            text = doc[i].get_text("text")
                            if text.strip():
                                pages.append(Document(page_content=text, metadata={"source": source_id, "page": i}))
                        # free memory per batch
                        gc.collect()
                    doc.close()

                if not pages:
                    logger.warning(f"No text extracted from {file_name}")
                    continue

                # Split into chunks
                chunks = self.splitter.split_documents(pages)

                # Add full metadata to chunks
                for i, chunk in enumerate(chunks):
                    chunk.metadata |= {
                        "source": source_id,
                        "file_path": file_path,
                        "chunk_id": i,
                        "total_chunks": len(chunks),
                    }

                all_docs.extend(chunks)
                logger.info(f"{file_name}: {len(chunks)} chunks loaded")

                # free memory
                del pages, chunks
                gc.collect()

            except Exception as e:
                logger.error(f"Error reading {file_name}: {e}")

        if not all_docs:
            raise ValueError("No documents loaded from PDF directory.")

        logger.info(f"Total loaded chunks: {len(all_docs)}")
        return all_docs