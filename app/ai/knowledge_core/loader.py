import os
from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger
import fitz #PyMuPDF
from app.config import CHUNK_SIZE,CHUNK_OVERLAP

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

    def load_documents(self) -> List[Document]:
        if not os.path.isdir(self.pdf_dir):
            raise FileNotFoundError(f"Directory missing: {self.pdf_dir}")

        pdf_files = [f for f in os.listdir(self.pdf_dir) if f.lower().endswith(".pdf")]
        if not pdf_files:
            raise FileNotFoundError("No PDFs found.")

        all_docs = []

        for file_name in pdf_files:
            file_path = os.path.join(self.pdf_dir, file_name)
            pages: List[Document] = []

            try:
                if not self.stream_mode:
                    # Normal mode: load entire PDF at once
                    doc = fitz.open(file_path)
                    for i in range(doc.page_count):
                        text = doc[i].get_text("text")
                        if text.strip():
                            pages.append(Document(page_content=text, metadata={"source": file_name, "page": i}))
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
                                pages.append(Document(page_content=text, metadata={"source": file_name, "page": i}))
                        # free memory per batch
                        import gc; gc.collect()
                    doc.close()

                if not pages:
                    logger.warning(f"No text extracted from {file_name}")
                    continue

                # Split into chunks
                chunks = self.splitter.split_documents(pages)

                # Add full metadata to chunks
                for i, chunk in enumerate(chunks):
                    chunk.metadata |= {
                        "source": os.path.splitext(file_name)[0],
                        "file_path": file_path,
                        "chunk_id": i,
                        "total_chunks": len(chunks),
                    }

                all_docs.extend(chunks)
                logger.info(f"{file_name}: {len(chunks)} chunks loaded")

                # free memory
                del pages, chunks
                import gc; gc.collect()

            except Exception as e:
                logger.error(f"Error reading {file_name}: {e}")

        if not all_docs:
            raise ValueError("No documents loaded from PDF directory.")

        logger.info(f"Total loaded chunks: {len(all_docs)}")
        return all_docs