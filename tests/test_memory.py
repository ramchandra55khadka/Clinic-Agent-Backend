"""Persistent conversation and long-term memory controls."""

from app.ai.chat_workflow import nodes
from app.db.session import SessionLocal
from app.models.conversation import Conversation, ConversationMessage
from app.services import memory as memory_service


class _RecordingRag:
    """Stands in for the RAG agent and captures the prompt it was handed."""

    def __init__(self):
        self.calls = []

    def answer(self, query, top_k=5, system_prompt=None):
        self.calls.append({"query": query, "system_prompt": system_prompt})
        return {"response": "Here is the answer.", "chunks": []}


def _chat(client, user, message, session_id=None):
    payload = {"message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    return client.post("/chat", headers=user["headers"], json=payload)


def test_chat_persists_conversation_messages_and_extracts_memory(client, make_user, monkeypatch):
    user = make_user()

    response = client.post(
        "/chat",
        headers=user["headers"],
        json={"message": "I prefer morning appointments."},
    )

    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]

    with SessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.session_id == session_id).first()
        assert conversation is not None
        messages = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id).all()
        assert [message.role for message in messages] == ["user", "assistant"]


def test_slot_memory_extraction_upserts_allowed_preferences(make_user):
    user = make_user()

    with SessionLocal() as db:
        account = db.get(memory_service.UserAccount, user["user"]["id"])
        saved = memory_service.extract_memories_from_message(
            db,
            user=account,
            message="I prefer morning appointments and remind me by email.",
        )
        memories = memory_service.list_memories(db, user_id=user["user"]["id"])
        assert {(memory.key, memory.value) for memory in saved} == {
            ("preferred_time", "Morning appointments"),
            ("contact_preference", "Email"),
        }
        assert {(memory.key, memory.value) for memory in memories} == {
            ("preferred_time", "Morning appointments"),
            ("contact_preference", "Email"),
        }

        memory_service.upsert_memory(db, user_id=user["user"]["id"], key="preferred_time", value="Evening appointments")
        memories = memory_service.list_memories(db, user_id=user["user"]["id"])
        assert len([memory for memory in memories if memory.key == "preferred_time"]) == 1
        assert next(memory.value for memory in memories if memory.key == "preferred_time") == "Evening appointments"


def test_health_information_is_not_saved_as_long_term_memory(make_user):
    user = make_user()

    with SessionLocal() as db:
        account = db.get(memory_service.UserAccount, user["user"]["id"])
        saved = memory_service.extract_memories_from_message(
            db,
            user=account,
            message="I prefer morning appointments because my fever is worse later.",
        )
        assert saved == []
        assert memory_service.list_memories(db, user_id=user["user"]["id"]) == []


def test_transcript_is_fed_back_into_the_prompt(client, make_user, monkeypatch):
    """A follow-up must be able to reference what was said in an earlier turn."""
    rag = _RecordingRag()
    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: rag)
    user = make_user()

    first = _chat(client, user, "Tell me about our doctors")
    assert first.status_code == 200, first.text
    session_id = first.json()["session_id"]

    rag.calls.clear()
    second = _chat(client, user, "What are their qualifications?", session_id=session_id)
    assert second.status_code == 200, second.text

    assert rag.calls, "the follow-up never reached an LLM-backed branch"
    system_prompt = rag.calls[-1]["system_prompt"]
    assert system_prompt is not None
    assert "Previous turns:" in system_prompt
    assert "Tell me about our doctors" in system_prompt


def test_anaphoric_followup_is_rewritten_for_retrieval(client, make_user, monkeypatch):
    """"What about her?" carries no searchable terms; the prior turn supplies them."""
    rag = _RecordingRag()
    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: rag)
    user = make_user()

    first = _chat(client, user, "Tell me about Dr. Koirala")
    session_id = first.json()["session_id"]

    rag.calls.clear()
    _chat(client, user, "What is his specialization?", session_id=session_id)

    assert rag.calls, "the follow-up never reached the RAG branch"
    query = rag.calls[-1]["query"]
    assert "Dr. Koirala" in query
    assert "his specialization" in query


def test_history_block_includes_summary_and_roles():
    block = memory_service.build_history_block(
        [{"role": "user", "content": "I need a cardiology slot"}, {"role": "assistant", "content": "Sure."}],
        summary="Patient wants a cardiology referral.",
    )
    assert "Earlier in this conversation (summary):" in block
    assert "Patient wants a cardiology referral." in block
    assert "Patient: I need a cardiology slot" in block
    assert "Assistant: Sure." in block


def test_history_block_is_empty_for_a_first_turn():
    assert memory_service.build_history_block([], "") == ""


def test_old_turns_are_compacted_into_the_rolling_summary(client, make_user, monkeypatch):
    """Beyond the live window, turns are folded into a summary, not dropped."""
    monkeypatch.setattr(memory_service, "_summary_llm", lambda: None)
    user = make_user()

    session_id = "session-for-summary"
    window = memory_service.HISTORY_TURNS * 2
    with SessionLocal() as db:
        for index in range(window + 4):
            memory_service.save_message(
                db,
                session_id=session_id,
                user_id=user["user"]["id"],
                role="user" if index % 2 == 0 else "assistant",
                content=f"turn number {index}",
            )

        summary = memory_service.refresh_summary(db, session_id=session_id, user_id=user["user"]["id"])
        assert summary, "nothing was compacted"
        # The oldest turns move into the summary...
        assert "turn number 0" in summary
        # ...and the newest stay verbatim in the live window, not duplicated.
        assert "turn number 1" in summary
        assert f"turn number {window + 3}" not in summary

        # The recent window is still returned verbatim on top of the summary.
        history = memory_service.recent_messages(db, session_id=session_id, user_id=user["user"]["id"])
        assert len(history) == window
        assert history[0]["content"] == "turn number 4"
        assert history[-1]["content"] == f"turn number {window + 3}"


def test_conversation_list_and_replay_endpoints(client, make_user, monkeypatch):
    user = make_user()

    first = _chat(client, user, "I would like a skin consultation")
    session_id = first.json()["session_id"]
    _chat(client, user, "Thank you", session_id=session_id)

    listed = client.get("/api/conversations/", headers=user["headers"])
    assert listed.status_code == 200, listed.text
    threads = listed.json()["conversations"]
    assert len(threads) == 1
    assert threads[0]["session_id"] == session_id
    assert threads[0]["title"].startswith("I would like a skin consultation")
    assert threads[0]["message_count"] == 4

    detail = client.get(f"/api/conversations/{session_id}", headers=user["headers"])
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert [turn["role"] for turn in body["messages"]] == ["user", "assistant", "user", "assistant"]
    assert body["messages"][0]["content"] == "I would like a skin consultation"
    assert not body["has_more"]


def test_conversation_replay_is_paginated_from_the_newest_turn(client, make_user, monkeypatch):
    user = make_user()

    session_id = "paginated-session"
    with SessionLocal() as db:
        for index in range(5):
            memory_service.save_message(
                db, session_id=session_id, user_id=user["user"]["id"], role="user", content=f"message {index}"
            )

    detail = client.get(f"/api/conversations/{session_id}?limit=2", headers=user["headers"])
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert [turn["content"] for turn in body["messages"]] == ["message 3", "message 4"]
    assert body["has_more"] is True

    oldest_id = body["messages"][0]["id"]
    earlier = client.get(
        f"/api/conversations/{session_id}?limit=2&before={oldest_id}", headers=user["headers"]
    )
    assert [turn["content"] for turn in earlier.json()["messages"]] == ["message 1", "message 2"]


def test_conversation_endpoints_are_user_scoped(client, make_user, monkeypatch):
    owner = make_user()
    intruder = make_user()

    session_id = _chat(client, owner, "my private consultation request").json()["session_id"]

    assert client.get("/api/conversations/", headers=intruder["headers"]).json()["conversations"] == []
    assert client.get(f"/api/conversations/{session_id}", headers=intruder["headers"]).status_code == 404
    assert client.delete(f"/api/conversations/{session_id}", headers=intruder["headers"]).status_code == 404

    # The owner's thread survived the intruder's failed delete.
    assert client.get(f"/api/conversations/{session_id}", headers=owner["headers"]).status_code == 200


def test_user_can_delete_a_conversation(client, make_user, monkeypatch):
    user = make_user()

    session_id = _chat(client, user, "delete this thread please").json()["session_id"]
    deleted = client.delete(f"/api/conversations/{session_id}", headers=user["headers"])
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/api/conversations/{session_id}", headers=user["headers"]).status_code == 404
    assert client.get("/api/conversations/", headers=user["headers"]).json()["conversations"] == []


def test_user_can_rename_a_conversation(client, make_user):
    user = make_user()

    session_id = "rename-me"
    with SessionLocal() as db:
        memory_service.save_message(
            db, session_id=session_id, user_id=user["user"]["id"], role="user", content="hello"
        )

    renamed = client.patch(
        f"/api/conversations/{session_id}",
        json={"title": "  Skin consult with Dr. Koirala  "},
        headers=user["headers"],
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Skin consult with Dr. Koirala"

    listed = client.get("/api/conversations/", headers=user["headers"])
    assert listed.json()["conversations"][0]["title"] == "Skin consult with Dr. Koirala"


def test_rename_is_user_scoped_and_validated(client, make_user):
    owner = make_user()
    intruder = make_user()

    session_id = "scoped-rename"
    with SessionLocal() as db:
        memory_service.save_message(
            db, session_id=session_id, user_id=owner["user"]["id"], role="user", content="private"
        )

    # Someone else's thread cannot be renamed (or even confirmed to exist).
    stolen = client.patch(
        f"/api/conversations/{session_id}", json={"title": "hijacked"}, headers=intruder["headers"]
    )
    assert stolen.status_code == 404

    # Blank and missing titles are rejected by the request schema.
    blank = client.patch(
        f"/api/conversations/{session_id}", json={"title": "   "}, headers=owner["headers"]
    )
    assert blank.status_code == 422
    missing = client.patch(f"/api/conversations/{session_id}", json={}, headers=owner["headers"])
    assert missing.status_code == 422

    # The owner's title survived the failed attempts.
    detail = client.get(f"/api/conversations/{session_id}", headers=owner["headers"])
    assert detail.json()["title"] != "hijacked"

    # An unknown thread is a 404 even for an authenticated caller.
    unknown = client.patch("/api/conversations/nope", json={"title": "x"}, headers=owner["headers"])
    assert unknown.status_code == 404


def test_conversation_endpoints_require_authentication(client):
    assert client.get("/api/conversations/").status_code == 401
    assert client.get("/api/conversations/anything").status_code == 401
    assert client.patch("/api/conversations/anything", json={"title": "x"}).status_code == 401
    assert client.delete("/api/conversations/anything").status_code == 401


def test_user_can_list_delete_and_clear_memories(client, make_user, monkeypatch):
    user = make_user()

    with SessionLocal() as db:
        first = memory_service.upsert_memory(db, user_id=user["user"]["id"], key="preferred_time", value="Morning appointments")
        memory_service.upsert_memory(db, user_id=user["user"]["id"], key="contact_preference", value="Email")
        assert first is not None
        first_id = first.id

    listed = client.get("/api/memories/", headers=user["headers"])
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["memories"]) == 2
    assert {memory["key"] for memory in listed.json()["memories"]} == {"preferred_time", "contact_preference"}

    patched = client.patch(f"/api/memories/{first_id}", headers=user["headers"], json={"value": "Evening appointments"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["value"] == "Evening appointments"

    deleted = client.delete(f"/api/memories/{first_id}", headers=user["headers"])
    assert deleted.status_code == 200, deleted.text

    listed_after_delete = client.get("/api/memories/", headers=user["headers"])
    assert len(listed_after_delete.json()["memories"]) == 1

    cleared = client.delete("/api/memories/", headers=user["headers"])
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["deleted"] == 1
    assert client.get("/api/memories/", headers=user["headers"]).json()["memories"] == []


def test_memory_is_user_scoped(client, make_user, monkeypatch):
    first = make_user()
    second = make_user()

    with SessionLocal() as db:
        memory_service.upsert_memory(db, user_id=first["user"]["id"], key="preferred_time", value="Morning appointments")

    response = client.get("/api/memories/", headers=second["headers"])
    assert response.status_code == 200
    assert response.json()["memories"] == []


def test_patching_a_memory_distinguishes_missing_from_rejected(client, make_user):
    """404 means "no such memory"; 422 means "the new value is not allowed".

    Both come back from the service as ``None``, so the route has to tell them
    apart — otherwise a rejected edit looks like a deleted row in the profile UI.
    """
    user = make_user()

    with SessionLocal() as db:
        memory = memory_service.upsert_memory(db, user_id=user["user"]["id"], key="preferred_time", value="Morning appointments")
        assert memory is not None
        memory_id = memory.id

    missing = client.patch("/api/memories/does-not-exist", headers=user["headers"], json={"value": "Evening appointments"})
    assert missing.status_code == 404, missing.text

    rejected = client.patch(
        f"/api/memories/{memory_id}",
        headers=user["headers"],
        json={"value": "Allergic to penicillin"},
    )
    assert rejected.status_code == 422, rejected.text

    with SessionLocal() as db:
        unchanged = memory_service.get_memory(db, user_id=user["user"]["id"], memory_id=memory_id)
        assert unchanged is not None
        assert unchanged.value == "Morning appointments"

    accepted = client.patch(f"/api/memories/{memory_id}", headers=user["headers"], json={"value": "Evening appointments"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["value"] == "Evening appointments"


def test_user_can_create_a_personalization(client, make_user):
    """``PUT /memories/{key}`` adds a slot by hand, then replaces it — never duplicates it."""
    user = make_user()

    created = client.put(
        "/api/memories/language",
        headers=user["headers"],
        json={"key": "language", "value": "Nepali"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["key"] == "language"
    assert created.json()["value"] == "Nepali"
    assert created.json()["kind"] == "preference"

    listed = client.get("/api/memories/", headers=user["headers"])
    assert [m["key"] for m in listed.json()["memories"]] == ["language"]

    # The slot is unique per user, so saving it again overwrites instead of stacking.
    replaced = client.put(
        "/api/memories/language",
        headers=user["headers"],
        json={"key": "language", "value": "Hindi"},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["value"] == "Hindi"

    listed = client.get("/api/memories/", headers=user["headers"]).json()["memories"]
    assert len(listed) == 1
    assert listed[0]["value"] == "Hindi"


def test_creating_a_personalization_rejects_bad_keys_and_values(client, make_user):
    """Unknown slot, mismatched path, or a policy-rejected value is a 422 — and writes nothing.

    None of these should ever surface as 404: the row never existed, so "not
    found" would send the profile UI hunting for a memory that was never there.
    """
    user = make_user()
    headers = user["headers"]

    unknown_key = client.put(
        "/api/memories/favourite_colour",
        headers=headers,
        json={"key": "favourite_colour", "value": "Blue"},
    )
    assert unknown_key.status_code == 422, unknown_key.text

    mismatched = client.put(
        "/api/memories/language",
        headers=headers,
        json={"key": "preferred_time", "value": "Morning appointments"},
    )
    assert mismatched.status_code == 422, mismatched.text

    blank = client.put("/api/memories/language", headers=headers, json={"key": "language", "value": "   "})
    assert blank.status_code == 422, blank.text

    medical = client.put(
        "/api/memories/preferred_doctor",
        headers=headers,
        json={"key": "preferred_doctor", "value": "Allergic to penicillin"},
    )
    assert medical.status_code == 422, medical.text

    listed = client.get("/api/memories/", headers=headers)
    assert listed.json()["memories"] == []


def test_creating_a_personalization_requires_authentication(client):
    response = client.put("/api/memories/language", json={"key": "language", "value": "Nepali"})
    assert response.status_code == 401

