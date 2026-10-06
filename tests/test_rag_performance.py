from langchain_core.documents import Document

from app.ai.knowledge_core.retrieval.retriever import Retriever


class _FakeStore:
    persist_directory = "vector_db/faiss"

    def __init__(self):
        self.db = object()
        self.calls = 0

    def query(self, text, k=5):
        self.calls += 1
        return [Document(page_content=f"{text}:{k}", metadata={"source": "test"})]

    def build_or_load(self, documents=None):  # pragma: no cover - replaced in tests
        raise AssertionError("unexpected FAISS load")


def test_retriever_reuses_loaded_store_without_loading_again(monkeypatch):
    store = _FakeStore()

    def fail_build_or_load(*args, **kwargs):  # pragma: no cover - called only on failure
        raise AssertionError("loaded stores should not reload FAISS")

    monkeypatch.setattr(store, "build_or_load", fail_build_or_load)

    retriever = Retriever(store=store)

    assert retriever.is_ready()


def test_retriever_caches_repeated_queries():
    store = _FakeStore()
    retriever = Retriever(store=store)

    first = retriever.retrieve("What is Nishant Care vision?", top_k=3)
    second = retriever.retrieve("  what   is nishant care vision?  ", top_k=3)

    assert store.calls == 1
    assert first[0].page_content == second[0].page_content


def test_retriever_reranks_candidates_by_query_terms():
    class Store(_FakeStore):
        def query(self, text, k=5):
            self.calls += 1
            return [
                Document(page_content="Nishant Care provides general healthcare services.", metadata={"source": "a"}),
                Document(
                    page_content="Our Vision is to become a trusted community healthcare center.",
                    metadata={"source": "b"},
                ),
            ]

    retriever = Retriever(store=Store())

    docs = retriever.retrieve("What is Nishant Care vision?", top_k=1)

    assert docs[0].metadata["source"] == "b"
