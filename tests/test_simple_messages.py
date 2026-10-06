from app.ai.chat_workflow.memory import get_session, save_session
from app.ai.chat_workflow.simple_messages import simple_message_response
from app.db.session import SessionLocal
from app.schemas.chat import ChatResponse


def test_standalone_greeting_bypasses_chat_workflow(client, make_user, monkeypatch):
    user = make_user()

    def fail_workflow(*args, **kwargs):  # pragma: no cover - called only on failure
        raise AssertionError("LLM workflow should not run for standalone greetings")

    monkeypatch.setattr("app.api.routes.doctor_info.run_clinic_chat", fail_workflow)

    response = client.post("/chat", headers=user["headers"], json={"message": "Hi!"})

    assert response.status_code == 200, response.text
    body = response.json()
    # The greeting is personalized with the patient's full profile name.
    assert body["response"] == "Hi Test User, how can I help you today?"
    assert body["intent"] == "fallback"
    assert body["data"] == {"simple_message": "greeting"}


def test_mixed_greeting_uses_normal_chat_workflow(client, make_user, monkeypatch):
    user = make_user()
    called = {"workflow": False}

    def fake_workflow(request, session_id, conversation_state, **kwargs):
        called["workflow"] = True
        return (
            ChatResponse(
                session_id=session_id,
                intent="booking",
                response="Booking flow started.",
                data={},
                chunks=None,
            ),
            conversation_state,
        )

    monkeypatch.setattr("app.api.routes.doctor_info.run_clinic_chat", fake_workflow)

    response = client.post(
        "/chat",
        headers=user["headers"],
        json={"message": "Hi, I want to book an appointment"},
    )

    assert response.status_code == 200, response.text
    assert called["workflow"] is True
    assert response.json()["intent"] == "booking"


def test_cancel_resets_active_workflow_without_chat_workflow(client, make_user, monkeypatch):
    user = make_user()
    session_id = "cancel-simple-message"
    with SessionLocal() as db:
        save_session(
            db,
            session_id,
            user["user"]["id"],
            {"mode": "booking", "booking": {"patient_name": "Asha"}},
        )

    def fail_workflow(*args, **kwargs):  # pragma: no cover - called only on failure
        raise AssertionError("LLM workflow should not run for standalone cancel")

    monkeypatch.setattr("app.api.routes.doctor_info.run_clinic_chat", fail_workflow)

    response = client.post(
        "/chat",
        headers=user["headers"],
        json={"session_id": session_id, "message": "cancel"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["response"] == "Okay, I have cancelled the current request."
    with SessionLocal() as db:
        assert get_session(db, session_id, user["user"]["id"]) == {"mode": None, "booking": {}}


def test_simple_help_and_identity_are_deterministic(client, make_user, monkeypatch):
    user = make_user()

    def fail_workflow(*args, **kwargs):  # pragma: no cover - called only on failure
        raise AssertionError("LLM workflow should not run for simple help or identity")

    monkeypatch.setattr("app.api.routes.doctor_info.run_clinic_chat", fail_workflow)

    help_response = client.post("/chat", headers=user["headers"], json={"message": "what can you do?"})
    identity_response = client.post("/chat", headers=user["headers"], json={"message": "are you a bot?"})

    assert help_response.status_code == 200, help_response.text
    assert "appointment booking" in help_response.json()["response"]
    assert identity_response.status_code == 200, identity_response.text
    assert identity_response.json()["response"].startswith("I am the clinic assistant.")


def test_polite_standalone_variants_are_deterministic(client, make_user, monkeypatch):
    user = make_user()

    def fail_workflow(*args, **kwargs):  # pragma: no cover - called only on failure
        raise AssertionError("LLM workflow should not run for polite standalone variants")

    monkeypatch.setattr("app.api.routes.doctor_info.run_clinic_chat", fail_workflow)

    cases = {
        "Nice to see you:": ("Glad I could help!", {"simple_message": "positive_feedback"}),
        "bye bye": ("Goodbye! Take care.", {"simple_message": "goodbye"}),
        "Nice to meet you:": ("Glad I could help!", {"simple_message": "positive_feedback"}),
    }

    for message, (expected_response, expected_data) in cases.items():
        response = client.post("/chat", headers=user["headers"], json={"message": message})

        assert response.status_code == 200, response.text
        assert response.json()["response"] == expected_response
        assert response.json()["data"] == expected_data


def test_greeting_is_personalized_and_falls_back_friendly():
    personalized = simple_message_response("Hi", session_id="s1", user_name="Sita Rai")
    assert personalized is not None
    assert personalized[0].response == "Hi Sita Rai, how can I help you today?"

    # No name yet (no profile): keep it warm but generic.
    unnamed = simple_message_response("hello", session_id="s1")
    assert unnamed is not None
    assert unnamed[0].response == "Hi there, how can I help you today?"

    # A blank/whitespace name is treated the same as a missing one.
    blank = simple_message_response("hey", session_id="s1", user_name="   ")
    assert blank is not None
    assert blank[0].response == "Hi there, how can I help you today?"

    # Only the greeting is personalized; other simple replies stay static.
    thanks = simple_message_response("thanks", session_id="s1", user_name="Sita Rai")
    assert thanks is not None
    assert thanks[0].response == "You're welcome!"
