from app.ai.agents.medical_search_agent import MedicalSearchAgent


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
            "doctor_name": "Dr. Unique Ashish Pun",
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


def test_booking_accepts_plain_patient_name_after_prompt(client, make_user):
    admin = make_user(role="admin")
    created = client.post(
        "/doctor-schedule/",
        headers=admin["headers"],
        json={
            "doctor_name": "Dr. Flow Ashish Pun",
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
    assert "\n\nNext: " in greeting.json()["response"]
