"""The assistant remembers the patient's name and recalls it on request."""

from uuid import uuid4

from app.services import memory as memory_service

DEFAULT_PASSWORD = "Sup3rSecret1"


def _chat(client, user, message, session_id=None):
    payload = {"message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    return client.post("/chat", headers=user["headers"], json=payload)


def test_stating_a_name_is_remembered_and_acknowledged(client, make_user):
    user = make_user()

    response = _chat(client, user, "My name is Sarmila")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "Sarmila" in body["response"]
    assert body["data"]["memory"] == {"key": "name", "value": "Sarmila"}

    listed = client.get("/api/memories/", headers=user["headers"])
    assert listed.status_code == 200, listed.text
    assert [m["key"] for m in listed.json()["memories"]] == ["name"]
    assert listed.json()["memories"][0]["value"] == "Sarmila"


def test_name_question_is_answered_from_memory_across_sessions(client, make_user):
    user = make_user()
    _chat(client, user, "My name is Sarmila")

    # A brand-new session still recalls the durable memory.
    for message in ("what is my name?", "what my name is", "who am I?"):
        response = _chat(client, user, message)
        assert response.status_code == 200, response.text
        assert response.json()["response"] == "Your name is Sarmila."


def test_name_question_falls_back_to_the_profile_name(client, make_user):
    user = make_user()  # the fixture sets the profile name to "Test User"

    response = _chat(client, user, "what is my name?")

    assert response.status_code == 200, response.text
    assert response.json()["response"] == "Your name is Test User."


def test_name_question_is_honest_when_nothing_is_known(client):
    email = f"nameless-{uuid4().hex[:10]}@example.com"
    registered = client.post("/api/auth/register", json={"email": email, "password": DEFAULT_PASSWORD})
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    response = client.post("/chat", headers=headers, json={"message": "what is my name?"})

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"name_known": False}
    assert "don't know your name" in response.json()["response"]


def test_greeting_prefers_the_remembered_name(client, make_user):
    user = make_user()
    _chat(client, user, "My name is Sarmila")

    response = _chat(client, user, "Hi")

    assert response.status_code == 200, response.text
    assert response.json()["response"] == "Hi Sarmila, how can I help you today?"


def test_stated_name_extraction_guards_against_false_positives():
    assert memory_service.stated_name("My name is Sarmila") == "Sarmila"
    assert memory_service.stated_name("my name's sarmila sharma") == "Sarmila Sharma"
    assert memory_service.stated_name("you can call me Sarmila") == "Sarmila"
    assert memory_service.stated_name("Please call me Sarmila.") == "Sarmila"
    assert memory_service.stated_name("I go by Sarmila") == "Sarmila"

    # A trailing sentence is trimmed and non-name utterances are ignored.
    assert memory_service.stated_name("my name is Sarmila and I need a doctor") == "Sarmila"
    assert memory_service.stated_name("I am from Nepal") is None
    assert memory_service.stated_name("I am 30 years old") is None
    assert memory_service.stated_name("Hi there") is None


def test_name_question_detection():
    assert memory_service.is_name_question("what is my name?")
    assert memory_service.is_name_question("what my name is")
    assert memory_service.is_name_question("do you know my name")
    assert memory_service.is_name_question("who am I?")
    assert not memory_service.is_name_question("My name is Sarmila")
    assert not memory_service.is_name_question("tell me about our doctors")
