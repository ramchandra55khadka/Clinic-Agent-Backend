"""Health, readiness and API metadata."""


def test_root_reports_running_api(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"


def test_health_endpoints_do_not_require_auth(client):
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.get("/health/live").json() == {"status": "alive"}


def test_readiness_checks_the_database(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"


def test_health_is_also_exposed_under_the_versioned_prefix(client):
    assert client.get("/api/health/live").json() == {"status": "alive"}


def test_responses_carry_request_id_and_security_headers(client):
    response = client.get("/health/live")
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_request_id_is_echoed_when_supplied(client):
    response = client.get("/health/live", headers={"X-Request-ID": "trace-me-123"})
    assert response.headers["X-Request-ID"] == "trace-me-123"