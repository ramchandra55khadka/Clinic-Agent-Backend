from datetime import datetime, timedelta

from app.ai.agents.medical_search_agent import MedicalSearchAgent
from app.ai.chat_workflow.extraction import parse_date
from app.core.config import settings


def test_chat_answers_who_is_available_today_without_doctor_id(client, doctor, make_user):
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "who is the doctor available today"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "availability"
    assert "doctor_id" not in body["data"].get("required", [])
    assert "Available doctors" in body["response"] or "No doctors" in body["response"]
    assert "doctors" in body["data"]


def test_chat_lists_doctors_without_date_prompt(client, doctor, make_user):
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Tell me the doctor available in Nishant Care?"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "availability"
    assert body["data"]["doctors"]
    assert "required" not in body["data"]
    assert "Doctors available at Nishant Care" in body["response"]
    assert "What date would you like" not in body["response"]


def test_chat_reads_doctor_details_from_database(client, doctor, make_user):
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Show doctor profiles and details"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "doctor_bio"
    assert body["data"]["source"] == "database"
    assert body["data"]["count"] >= 1
    assert body["data"]["doctors"][0]["doctor_name"] == doctor["schedule"]["doctor_name"]
    assert "Specialization" in body["response"]
    assert "Schedule" in body["response"]


def test_chat_reads_specific_doctor_detail_from_database(client, doctor, make_user):
    patient = make_user()
    doctor_id = doctor["schedule"]["id"]
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": f"Tell me details about doctor id {doctor_id}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "doctor_bio"
    assert body["data"]["source"] == "database"
    assert body["data"]["count"] == 1
    assert body["data"]["doctors"][0]["id"] == doctor_id


def test_chat_reads_doctor_name_followup_from_database(client, doctor, make_user):
    patient = make_user()
    first = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Show doctor profiles and details"},
    )
    assert first.status_code == 200, first.text

    doctor_name = doctor["schedule"]["doctor_name"]
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": first.json()["session_id"], "message": f"Tell me about {doctor_name}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "doctor_bio"
    assert body["data"]["source"] == "database"
    assert body["data"]["count"] == 1
    assert body["data"]["doctors"][0]["doctor_name"] == doctor_name


def test_chat_suggests_close_doctor_name_for_typo(client, doctor, make_user):
    patient = make_user()
    doctor_name = doctor["schedule"]["doctor_name"]
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Tell me about Tost Sharma"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "doctor_bio"
    assert body["data"]["source"] == "database"
    assert body["data"]["clarification"] is True
    assert body["data"]["required"] == ["doctor_name"]
    assert body["data"]["clarification_options"] == [doctor_name]
    assert f"Did you mean {doctor_name}" in body["response"]


def test_chat_routes_general_medical_question_to_web_agent(client, make_user, monkeypatch):
    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {"title": "Fever - NHS", "link": "https://www.nhs.uk/conditions/fever/", "snippet": "Advice about fever."}
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
    body = response.json()
    assert body["intent"] == "medical_web"
    assert body["data"]["provider"] == "duckduckgo"
    assert body["data"]["sources"]


def test_booking_after_availability_accepts_doctor_name(client, make_user):
    admin = make_user(role="admin")
    created = client.post(
        "/doctor-schedule/",
        headers=admin["headers"],
        json={
            "first_name": "Unique",
            "last_name": "Ashish Pun",
            "specialization": "General Medicine",
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "break_start": "13:00:00",
            "break_end": "14:00:00",
            "slot_duration": 30,
        },
    )
    assert created.status_code == 200, created.text
    schedule = created.json()
    patient = make_user()
    first = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "which doctor is available today"},
    )
    assert first.status_code == 200, first.text
    session_id = first.json()["session_id"]

    doctor_name = schedule["doctor_name"]
    second = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": f"Book appointment for me for {doctor_name}"},
    )

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["intent"] == "booking"
    assert "doctor_id" not in body["data"].get("required", [])
    assert body["data"]["booking"]["doctor_id"] == schedule["id"]


def test_booking_doctor_prompt_lists_names_without_ids(client, doctor, make_user):
    patient = make_user()
    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "I want to book an appointment"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "booking"
    assert "Available doctors" in body["response"]
    assert doctor["schedule"]["doctor_name"] in body["response"]
    assert "(ID " not in body["response"]
    assert "doctor ID" not in body["response"]


def test_booking_accepts_plain_patient_name_after_prompt(client, make_user):
    admin = make_user(role="admin")
    created = client.post(
        "/doctor-schedule/",
        headers=admin["headers"],
        json={
            "first_name": "Flow",
            "last_name": "Ashish Pun",
            "specialization": "General Medicine",
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "break_start": "13:00:00",
            "break_end": "14:00:00",
            "slot_duration": 30,
        },
    )
    assert created.status_code == 200, created.text
    schedule = created.json()
    patient = make_user()

    first = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "which doctor is available today"},
    )
    session_id = first.json()["session_id"]

    second = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": f"Book appointment for me for {schedule['doctor_name']}"},
    )
    assert second.status_code == 200, second.text

    third = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": "Please book 3:00 PM."},
    )
    assert third.status_code == 200, third.text
    assert third.json()["data"]["required"] == ["patient_name"]

    fourth = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": "Pramish Sharma"},
    )

    assert fourth.status_code == 200, fourth.text
    body = fourth.json()
    assert body["data"]["booking"]["patient_name"] == "Pramish Sharma"
    assert body["data"]["required"] == ["age"]


def test_booking_asks_for_final_confirmation_before_saving(client, doctor, make_user):
    patient = make_user()
    session_id = None

    steps = [
        (
            {
                "message": "I want to book appointment at 9:00 AM.",
                "doctor_id": doctor["schedule"]["id"],
                "appointment_date": "2030-01-07",
                "appointment_time": "09:00:00",
            },
            "patient_name",
        ),
        ({"message": "Ramchandra Khada"}, "age"),
        ({"message": "33"}, "sex"),
        ({"message": "Male"}, "email"),
        ({"message": "ram@example.com"}, "phone"),
    ]

    for payload, required in steps:
        if session_id:
            payload["session_id"] = session_id
        response = client.post("/chat", headers=patient["headers"], json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        session_id = body["session_id"]
        assert body["data"]["required"] == [required]

    pending = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": "3432423432"},
    )
    assert pending.status_code == 200, pending.text
    body = pending.json()
    assert body["data"]["required"] == ["confirmation"]
    assert body["data"]["awaiting_confirmation"] is True
    assert "Do you want to confirm the appointment" in body["response"]
    assert "2030-01-07" in body["response"]
    assert "9:00 AM" in body["response"]
    assert "appointment" not in body["data"]

    confirmed = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": "yes"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["data"]["status"] == "success"
    assert body["data"]["appointment"]["patient_name"] == "Ramchandra Khada"
    assert "Your appointment is confirmed" in body["response"]


def test_booking_explains_invalid_field_answers(client, doctor, make_user):
    patient = make_user()
    session_id = None

    steps = [
        (
            {
                "message": "I want to book appointment at 9:00 AM.",
                "doctor_id": doctor["schedule"]["id"],
                "appointment_date": "2030-01-07",
                "appointment_time": "09:00:00",
            },
            "patient_name",
        ),
        ({"message": "Ramchandra Khada"}, "age"),
        ({"message": "33"}, "sex"),
        ({"message": "Male"}, "email"),
    ]

    for payload, required in steps:
        if session_id:
            payload["session_id"] = session_id
        response = client.post("/chat", headers=patient["headers"], json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        session_id = body["session_id"]
        assert body["data"]["required"] == [required]

    invalid_email = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": "ram"},
    )
    assert invalid_email.status_code == 200, invalid_email.text
    body = invalid_email.json()
    assert body["data"]["required"] == ["email"]
    assert "Please enter a valid email address" in body["response"]

    valid_email = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": "ram@example.com"},
    )
    assert valid_email.status_code == 200, valid_email.text
    assert valid_email.json()["data"]["required"] == ["phone"]


def test_booking_confirmation_allows_detail_edits_before_confirming(client, doctor, make_user):
    patient = make_user()
    session_id = None

    steps = [
        (
            {
                "message": "I want to book appointment at 9:00 AM.",
                "doctor_id": doctor["schedule"]["id"],
                "appointment_date": "2030-01-07",
                "appointment_time": "09:00:00",
            },
            "patient_name",
        ),
        ({"message": "Ramchandra Khada"}, "age"),
        ({"message": "33"}, "sex"),
        ({"message": "Male"}, "email"),
        ({"message": "ram@example.com"}, "phone"),
    ]

    for payload, _required in steps:
        if session_id:
            payload["session_id"] = session_id
        response = client.post("/chat", headers=patient["headers"], json=payload)
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]

    pending = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": "3432423432"},
    )
    assert pending.status_code == 200, pending.text

    edited = client.post(
        "/chat",
        headers=patient["headers"],
        json={
            "session_id": session_id,
            "message": (
                "patient name is Sita Sharma. age is 34. sex Female. "
                "email sita@example.com. phone 9800000000. date 2030-01-07. time 09:00"
            ),
        },
    )

    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["data"]["required"] == ["confirmation"]
    assert body["data"]["booking"]["patient_name"] == "Sita Sharma"
    assert body["data"]["booking"]["age"] == 34
    assert body["data"]["booking"]["sex"] == "Female"
    assert body["data"]["booking"]["email"] == "sita@example.com"
    assert body["data"]["booking"]["phone"] == "9800000000"


def test_booking_accepts_common_date_typos():
    tomorrow = parse_date("tommrow")
    assert tomorrow is not None

    october = parse_date("octuber 4")
    assert october is not None
    assert october.month == 10
    assert october.day == 4


def test_parse_date_accepts_flexible_typed_formats():
    # Single-digit month/day and separators other than "-".
    assert parse_date("2026-10-3").isoformat() == "2026-10-03"
    assert parse_date("2026/10/3").isoformat() == "2026-10-03"
    assert parse_date("2026.10.3").isoformat() == "2026-10-03"

    # Single-digit month as well as day.
    assert parse_date("2026-1-5").isoformat() == "2026-01-05"

    # Year-first with a spelled-out month (the format in the bug report).
    assert parse_date("2026-November-2").isoformat() == "2026-11-02"
    assert parse_date("2026 October 3").isoformat() == "2026-10-03"

    # Month-first and day-first spellings.
    assert parse_date("Nov 2 2026").isoformat() == "2026-11-02"
    assert parse_date("2 November 2026").isoformat() == "2026-11-02"
    assert parse_date("2nd Nov 2026").isoformat() == "2026-11-02"
    assert parse_date("November 2") is not None

    # Impossible calendar dates are still rejected rather than crashing.
    assert parse_date("2026-09-55") is None
    assert parse_date("2026-February-30") is None


def test_booking_accepts_typed_non_padded_date(client, doctor, make_user):
    patient = make_user()
    first = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "I want to make appointment", "doctor_id": doctor["schedule"]["id"]},
    )
    assert first.status_code == 200, first.text
    session_id = first.json()["session_id"]

    # A future date with a single-digit day so the non-padded format stays valid
    # no matter when the suite runs (a past date would be rejected instead).
    future = datetime.now(settings.clinic_tzinfo).date() + timedelta(days=1)
    while future.day >= 10:
        future += timedelta(days=1)
    expected = future.isoformat()
    month_name = future.strftime("%B")

    # The exact formats reported as "cannot type date" must be understood.
    for typed in (f"{future.year}-{future.month}-{future.day}", f"{future.year}-{month_name}-{future.day}"):
        response = client.post(
            "/chat",
            headers=patient["headers"],
            json={"session_id": session_id, "message": typed},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["intent"] == "booking"
        assert body["data"]["booking"]["date"] == expected
        assert "date" not in body["data"].get("required", [])


def test_booking_invalid_date_does_not_crash(client, doctor, make_user):
    patient = make_user()
    first = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "I want to make appointment", "doctor_id": doctor["schedule"]["id"]},
    )
    assert first.status_code == 200, first.text

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": first.json()["session_id"], "message": "2026-09-55"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "booking"
    assert body["data"]["required"] == ["date"]
    assert "date" in body["response"].lower()


def test_booking_past_date_is_validated_before_confirmation(client, doctor, make_user):
    patient = make_user()

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={
            "message": "Book appointment at 10 AM on 2020-01-01",
            "doctor_id": doctor["schedule"]["id"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["required"] == ["date"]
    assert "past" in body["response"].lower()
    assert "awaiting_confirmation" not in body["data"]


def test_booking_past_time_today_is_validated_before_confirmation(client, doctor, make_user):
    now = datetime.now(settings.clinic_tzinfo)
    if now.hour == 0 and now.minute < 30:
        return

    past_hour = max(now.hour - 1, 0)
    patient = make_user()

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={
            "message": f"Book appointment today at {past_hour:02d}:00",
            "doctor_id": doctor["schedule"]["id"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["required"] == ["time"]
    assert "already passed" in body["response"].lower()
    assert "awaiting_confirmation" not in body["data"]


def test_booking_bad_doctor_id_is_cleared_and_prompts_for_doctor(client, make_user):
    patient = make_user()

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Book doctor id 98765 tomorrow at 10 AM"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "booking"
    assert body["data"]["required"] == ["doctor_id"]
    assert "doctor_id" not in body["data"]["booking"]
    assert "Which doctor would you like" in body["response"]


def test_doctor_question_interrupts_booking_mode():
    from app.ai.chat_workflow.nodes import route_intent

    state = {
        "message": "Tell me about our doctors",
        "conversation": {"mode": "booking", "booking": {"doctor_id": 98765}},
        "patient": None,
        "history": [],
        "summary": "",
        "long_term_memories": [],
    }

    assert route_intent(state)["intent"] == "doctor_bio"


def test_general_medical_science_question_uses_duckduckgo_agent(client, make_user, monkeypatch):
    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {
                "title": "Medical science",
                "link": "https://medlineplus.gov/",
                "snippet": "Medical science studies health, disease, diagnosis and treatment.",
            }
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: None)
    patient = make_user()

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "What is Medical Science"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "medical_web"
    assert body["data"]["provider"] == "duckduckgo"


def test_who_are_you_stays_on_assistant_identity():
    from app.ai.chat_workflow.nodes import fallback_node, route_intent

    state = {
        "message": "who are you",
        "conversation": {},
        "patient": None,
        "history": [],
        "summary": "",
        "long_term_memories": [],
    }

    assert route_intent(state)["intent"] == "fallback"
    result = fallback_node(state)
    assert "clinic assistant" in result["response"].lower()
    assert result["data"]["assistant_identity"] is True


def test_non_clinic_general_questions_are_out_of_scope(client, make_user):
    patient = make_user()

    for message in ["Write Python code for Django", "Who won the football match?", "Explain quantum computing"]:
        response = client.post("/chat", headers=patient["headers"], json={"message": message})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["intent"] == "out_of_scope"
        assert body["data"]["scope"] == "out_of_scope"
        assert "healthcare" in body["response"].lower()


def test_short_medical_topics_are_in_scope_for_web_search(client, make_user, monkeypatch):
    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {"title": "Health topic", "link": "https://medlineplus.gov/", "snippet": "Trusted health information."}
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: None)
    patient = make_user()

    for message in ["Openheart surjery", "telemedicine", "cardiology", "how to become out of alcholic habit"]:
        response = client.post("/chat", headers=patient["headers"], json={"message": message})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["intent"] == "medical_web"
        assert body["data"]["provider"] == "duckduckgo"


def test_our_doctors_question_stays_on_doctor_bio_path(client, make_user, monkeypatch):
    from app.ai.chat_workflow import nodes

    class FakeRagAgent:
        def answer(self, query, top_k=5, system_prompt=None):
            return {"response": "Our doctors include clinic specialists.", "chunks": []}

    monkeypatch.setattr(nodes, "_get_rag_agent", lambda: FakeRagAgent())
    patient = make_user()

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Tell me about our doctors"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["intent"] == "doctor_bio"


def test_medical_search_filters_untrusted_domains(monkeypatch):
    from app.ai.agents import medical_search_agent

    class FakeDDGS:
        def text(self, query, max_results):
            return [
                {"title": "Forum answer", "href": "https://random.example/health", "body": "Nope"},
                {"title": "Medical science", "href": "https://medlineplus.gov/health.html", "body": "Trusted"},
            ]

    monkeypatch.setattr(medical_search_agent, "DDGS", lambda: FakeDDGS())
    results = MedicalSearchAgent()._duckduckgo_search("What is medical science")

    assert results == [
        {"title": "Medical science", "link": "https://medlineplus.gov/health.html", "snippet": "Trusted"}
    ]


def test_trusted_medical_source_allows_subdomains():
    agent = MedicalSearchAgent()

    assert agent._is_trusted_medical_source("https://www.cdc.gov/flu/")
    assert agent._is_trusted_medical_source("https://medlineplus.gov/health.html")
    assert not agent._is_trusted_medical_source("https://notcdc.gov/flu")


def test_general_question_interrupts_booking_mode(client, make_user, monkeypatch):
    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {
                "title": "Medical science",
                "link": "https://medlineplus.gov/",
                "snippet": "Medical science studies health, disease, diagnosis and treatment.",
            }
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: None)
    patient = make_user()

    started = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Book an appointment for me"},
    )
    assert started.status_code == 200, started.text

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": started.json()["session_id"], "message": "What is medical science"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "medical_web"
    assert body["data"]["provider"] == "duckduckgo"


def test_open_heart_surgery_is_medical_web_not_availability(client, make_user, monkeypatch):
    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {
                "title": "Heart surgery",
                "link": "https://www.nhs.uk/conditions/coronary-artery-bypass-graft-cabg/",
                "snippet": "Open heart surgery is surgery performed on the heart.",
            }
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: None)
    patient = make_user()

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "What is open heart surgery"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "medical_web"
    assert "appointment_date" not in body["data"].get("required", [])


def test_medical_agent_returns_sources_when_llm_fails(monkeypatch):
    class BrokenLlm:
        def invoke(self, _prompt):
            raise RuntimeError("quota")

    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {"title": "Medical science", "link": "https://medlineplus.gov/", "snippet": "Trusted source."}
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: BrokenLlm())

    result = MedicalSearchAgent().answer("What is medical science")

    assert result["data"]["search_available"] is True
    assert "Trusted source" in result["response"]
    assert "https://medlineplus.gov/" not in result["response"]


def test_medical_agent_accepts_llm_content_blocks(monkeypatch):
    class BlockLlm:
        def invoke(self, _prompt):
            return [{"type": "text", "text": "Use acetaminophen as directed and seek care for severe symptoms."}]

    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {"title": "Fever", "link": "https://www.nhs.uk/conditions/fever/", "snippet": "Trusted source."}
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: BlockLlm())

    result = MedicalSearchAgent().answer("What should I do for fever")

    assert result["response"] == "Use acetaminophen as directed and seek care for severe symptoms."
    assert result["data"]["search_available"] is True


def test_medical_agent_without_llm_returns_answer_not_source_list(monkeypatch):
    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {
                "title": "Medicine",
                "link": "https://en.wikipedia.org/wiki/Medicine",
                "snippet": "Medicine is the science and practice of caring for patients, managing diagnosis, prognosis, prevention, treatment and palliation.",
            }
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: None)

    result = MedicalSearchAgent().answer("What is medical science")

    assert "Medicine is the science and practice" in result["response"]
    assert "Here are reliable sources" not in result["response"]
    assert "https://" not in result["response"]
    assert result["data"]["sources"]


def test_medical_agent_fallback_cleans_noisy_definition_snippets(monkeypatch):
    monkeypatch.setattr(
        MedicalSearchAgent,
        "_duckduckgo_search",
        lambda _self, _query: [
            {
                "title": "Medical research",
                "link": "https://en.wikipedia.org/wiki/Medical_research",
                "snippet": (
                    "A sub-set of biomedical sciences is the science of clinical laboratory diagnosis. [2] "
                    "There are at least 45 different specialisms. Cell culture vials The University of Florida "
                    "Cancer and Genetics Research Complex is an integrated medical research facility."
                ),
            },
            {
                "title": "Health sciences",
                "link": "https://medlineplus.gov/healthtopics.html",
                "snippet": "Medical science studies health, disease, diagnosis, prevention and treatment.",
            },
        ],
    )
    monkeypatch.setattr(MedicalSearchAgent, "_get_llm", lambda _self: None)

    result = MedicalSearchAgent().answer("What is medical science")

    assert result["response"].startswith("Medical science studies health")
    assert "[2]" not in result["response"]
    assert "Cell culture vials" not in result["response"]
    assert "Sources checked:" in result["response"]
    assert "https://" not in result["response"]


def test_chat_responses_use_consistent_next_step_format(client, doctor, make_user):
    patient = make_user()

    availability = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "who is available today"},
    )
    assert availability.status_code == 200, availability.text
    assert "\n\nNext: " in availability.json()["response"]

    greeting = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "Hello"},
    )
    assert greeting.status_code == 200, greeting.text
    assert greeting.json()["response"] == "Hi Test User, how can I help you today?"
    assert greeting.json()["data"] == {"simple_message": "greeting"}
