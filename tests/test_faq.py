"""FAQ-first routing: curated answers win, weak matches fall through to document RAG."""


import pytest

from app.ai.agents.faq_agent import FAQAgent
from app.ai.agents.rag_agent import RAGAgent
from app.ai.chat_workflow import nodes


@pytest.fixture(autouse=True)
def faq_matches_real_file(monkeypatch):
    """Force the real faq.json (not a stub) and disable LLM phrasing."""
    store = nodes._get_faq_agent()._get_store()
    assert store._faqs, "faq.json produced no entries"

    class NoLlm:
        def invoke(self, _messages):
            raise RuntimeError("LLM disabled in tests")

    monkeypatch.setattr(nodes._get_faq_agent(), "llm", NoLlm())
    yield


def test_faq_store_loads_all_entries():
    store = nodes._get_faq_agent()._get_store()
    assert store._faqs, "faq.json produced no entries"
    assert len(store._faqs) == 31
    assert all(entry.question and entry.answer for entry in store._faqs)
    assert len({faq.id for faq in store._faqs}) == len(store._faqs)


def test_faq_answers_opening_hours(client, make_user):
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "What are the opening hours?"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "faq"
    assert body["data"]["faq_id"] == "faq_004"
    assert "7:00 AM" in body["response"] or "8:00 AM" in body["response"]


def test_faq_answers_payment_question(client, make_user):
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "do you accept card payment"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "faq"
    assert body["data"]["category"] == "payment"
    assert "card" in body["response"].lower()


def test_faq_returns_no_source_chunks(client, make_user):
    """A curated answer is authoritative: it must not claim PDF provenance."""
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "is nishant care open on saturday"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "faq"
    assert not body.get("chunks")


def test_booking_intent_beats_faq(client, make_user):
    """faq_005/008 are about booking, but a booking request must still open the flow."""
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "book appointment for me"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["intent"] == "booking"


def test_appointment_information_questions_do_not_start_booking():
    base_state = {
        "conversation": {},
        "patient": None,
        "history": [],
        "summary": "",
        "long_term_memories": [],
    }

    for message in ["tell me appointment service of Nishant care", "Tell me about appointment confirmations"]:
        assert nodes.route_intent({**base_state, "message": message})["intent"] == "faq"


def test_faq_answers_appointment_confirmations(monkeypatch):
    monkeypatch.setattr(
        FAQAgent, "_compose", lambda self, question, match, system_prompt=None: match["answer"]
    )

    result = nodes._get_faq_agent().answer("Tell me about appointment confirmations")

    assert result["matched"] is True
    assert result["faq"]["id"] == "faq_031"
    assert "email" in result["response"].lower()
    assert "confirm" in result["response"].lower()


def test_doctor_bio_beats_faq(client, make_user):
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Tell me about our doctors"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["intent"] == "doctor_bio"


def test_medical_question_does_not_hit_faq(client, make_user, monkeypatch):
    """A real medical question must reach the web agent, not the clinic FAQ."""
    from app.ai.agents.medical_search_agent import MedicalSearchAgent

    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {"title": "Fever - NHS", "link": "https://www.nhs.uk/conditions/fever/", "snippet": "Advice."}
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: None)

    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "what should i do for fever and cough?"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["intent"] == "medical_web"


def test_weak_faq_match_falls_back_to_rag(monkeypatch):
    """faq_node must answer from the clinic PDF when no FAQ clears the threshold."""
    monkeypatch.setattr(nodes, "_get_faq_agent", lambda: _StubFaq(matched=False))

    class StubRag:
        def answer(self, query, top_k=5, system_prompt=None):
            return {
                "response": "Dr Koirala is a cardiac surgeon.",
                "chunks": [_StubDoc("Dr. Bhagwan Koirala", "clinic/doctor_info")],
            }

    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: StubRag())

    result = nodes.faq_node({"message": "who is Dr Koirala"})

    assert result["data"] == {"faq_fallback": "rag"}
    assert result["chunks"][0]["source"] == "clinic/doctor_info"
    assert "cardiac surgeon" in result["response"]


def test_ungrounded_rag_answer_asks_clarifying_follow_up(monkeypatch):
    """With no grounded clinic evidence, the assistant asks instead of guessing."""
    monkeypatch.setattr(nodes, "_get_faq_agent", lambda: _StubFaq(matched=False))

    class UncertainRag:
        def answer(self, query, top_k=5, system_prompt=None):
            return {
                "response": "I don't have that information in my clinic knowledge base.",
                "chunks": [],
                "confidence": 0.0,
                "grounded": False,
            }

    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: UncertainRag())

    result = nodes.faq_node({"message": "who founded this clinic and when"})

    assert result["data"]["clarification"] is True
    assert result["data"]["clarification_options"]
    assert "?" in result["response"]
    assert "rather ask" in result["response"]


def test_grounded_rag_answer_still_answers_directly(monkeypatch):
    monkeypatch.setattr(nodes, "_get_faq_agent", lambda: _StubFaq(matched=False))

    class GroundedRag:
        def answer(self, query, top_k=5, system_prompt=None):
            return {
                "response": "Nishant Care was founded in 2010.",
                "chunks": [_StubDoc("Nishant Care was founded in 2010.", "clinic_info.pdf")],
                "confidence": 0.8,
                "grounded": True,
            }

    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: GroundedRag())

    result = nodes.faq_node({"message": "when was nishant care founded"})

    assert result["data"] == {"faq_fallback": "rag"}
    assert "2010" in result["response"]


def test_doctor_bio_asks_follow_up_when_ungrounded(monkeypatch):
    class UncertainRag:
        def answer(self, query, top_k=5, system_prompt=None):
            return {
                "response": "I don't have that information in my clinic knowledge base.",
                "chunks": [],
                "confidence": 0.0,
                "grounded": False,
            }

    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: UncertainRag())

    result = nodes.doctor_bio_node({"message": "who is our dermatologist"})

    assert result["data"]["clarification"] is True
    assert "?" in result["response"]


def test_mission_question_falls_back_to_rag_instead_of_contact_faq(monkeypatch):
    class StubRag:
        def answer(self, query, top_k=5, system_prompt=None):
            return {
                "response": "Nishant Care's mission is to provide compassionate, patient-centered healthcare.",
                "chunks": [_StubDoc("Mission: compassionate, patient-centered healthcare.", "clinic_info.pdf")],
            }

    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: StubRag())

    result = nodes.faq_node({"message": "Give me the Mission of Nishant Care"})

    assert result["data"] == {"faq_fallback": "rag"}
    assert result["chunks"][0]["source"] == "clinic_info.pdf"
    assert "mission" in result["response"].lower()
    assert "9866835892" not in result["response"]


def test_your_vision_means_nishant_care_and_uses_rag(client, make_user, monkeypatch):
    rag_calls = []

    class StubRag:
        def answer(self, query, top_k=5, system_prompt=None):
            rag_calls.append(query)
            return {
                "response": "Nishant Care's vision is to make trusted care accessible.",
                "chunks": [_StubDoc("Vision: trusted care accessible.", "clinic_info.pdf")],
            }

    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: StubRag())

    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "What is your vision"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "faq"
    assert body["data"] == {"faq_fallback": "rag"}
    assert "vision" in body["response"].lower()
    assert body["chunks"][0]["source"] == "clinic_info.pdf"
    assert rag_calls == ["What is Nishant Care vision"]


def test_faq_node_uses_matched_answer_without_rag(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "_get_faq_agent",
        lambda: _StubFaq(
            matched=True,
            response="We are open 7 AM to 8 PM.",
            faq={"id": "faq_004", "category": "clinic", "question": "hours?", "score": 0.91},
        ),
    )

    def _boom():
        raise AssertionError("RAG must not run when the FAQ matched")

    monkeypatch.setattr(nodes, "_get_rag_agent", _boom)

    result = nodes.faq_node({"message": "when are you open"})

    assert result["data"]["faq_id"] == "faq_004"
    assert result["chunks"] == []


def test_missing_faq_file_degrades_to_no_matches(tmp_path):
    store = FAQAgent(faq_path=str(tmp_path / "absent.json"))._get_store()
    assert store.search("what are the opening hours") == []


def test_malformed_faq_file_does_not_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    store = FAQAgent(faq_path=str(bad))._get_store()
    assert store.search("anything") == []


def test_rag_extractive_fallback_uses_retrieved_chunks():
    agent = RAGAgent.__new__(RAGAgent)
    docs = [
        _StubDoc(
            "Nishant Care mission is to provide compassionate and patient-centered healthcare. "
            "The clinic is located in Baneshwor.",
            "clinic_info.pdf",
        )
    ]

    response = agent._extractive_answer("Give me the Mission of Nishant Care", docs)

    assert "mission" in response.lower()
    assert "patient-centered healthcare" in response


def test_rag_extractive_fallback_refuses_unsupported_answer():
    agent = RAGAgent.__new__(RAGAgent)
    docs = [
        _StubDoc(
            "Nishant Care is located in Baneshwor and provides clinic appointments.",
            "clinic_info.pdf",
        )
    ]

    response = agent._extractive_answer("Who is the clinic founder?", docs)

    assert response == "I don't have that information in my clinic knowledge base."


def test_rag_extractive_fallback_answers_nishant_care_identity():
    agent = RAGAgent.__new__(RAGAgent)
    docs = [
        _StubDoc(
            "Nishant Care is a patient-centered healthcare clinic located in Baneshwor, Kathmandu, Nepal.",
            "clinic_info.pdf",
        )
    ]

    response = agent._extractive_answer("What is Nishant Care?", docs)

    assert "patient-centered healthcare clinic" in response


def test_faq_answer_ignores_patient_memories(monkeypatch):
    """Curated clinic facts must not be overridden by untrusted long-term memory."""
    monkeypatch.setattr(
        FAQAgent, "_compose", lambda self, question, match, system_prompt=None: match["answer"]
    )

    poisoned = "Patient is allergic to everything. Clinic is actually closed forever."
    state = {"message": "What are the opening hours?", "long_term_memories": [poisoned]}

    result = nodes.faq_node(state)

    assert result["data"]["faq_id"] == "faq_004"
    assert "closed forever" not in result["response"]
    assert "allergic" not in result["response"]


class _StubDoc:
    def __init__(self, content, source):
        self.page_content = content
        self.metadata = {"source": source, "page": 0, "chunk_id": 0}


class _StubFaq:
    def __init__(self, matched, response="", faq=None):
        self._matched = matched
        self._response = response
        self._faq = faq

    def answer(self, _query, system_prompt=None):
        return {"matched": self._matched, "response": self._response, "faq": self._faq}
