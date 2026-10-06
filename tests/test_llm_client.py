from app.ai import llm_client


def test_wait_for_llm_slot_spaces_requests(monkeypatch):
    sleeps: list[float] = []
    times = iter([10.0, 11.0])

    monkeypatch.setattr(llm_client, "LLM_REQUEST_DELAY_SECONDS", 2.0)
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(llm_client.time, "sleep", sleeps.append)
    monkeypatch.setattr(llm_client, "_last_llm_request_at", 9.0)

    llm_client._wait_for_llm_slot()

    assert sleeps == [1.0]
    assert llm_client._last_llm_request_at == 11.0


def test_wait_for_llm_slot_can_be_disabled(monkeypatch):
    sleeps: list[float] = []

    monkeypatch.setattr(llm_client, "LLM_REQUEST_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(llm_client.time, "sleep", sleeps.append)

    llm_client._wait_for_llm_slot()

    assert sleeps == []
