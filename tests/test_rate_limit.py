"""Rate limiter unit tests (the in-process fixed window)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.core.rate_limit as rate_limit_module
from app.core.rate_limit import WindowStore, rate_limit


def test_allows_up_to_the_limit_then_blocks():
    store = WindowStore()
    results = [store.hit("scope", "key", 2, 60)[0] for _ in range(3)]
    assert results == [True, True, False]


def test_reports_retry_after_when_blocked():
    store = WindowStore()
    store.hit("scope", "key", 1, 30)
    allowed, retry_after = store.hit("scope", "key", 1, 30)

    assert allowed is False
    assert 0 < retry_after <= 30


def test_window_resets_once_it_expires(monkeypatch):
    store = WindowStore()
    clock = {"now": 1_000.0}
    monkeypatch.setattr(rate_limit_module.time, "monotonic", lambda: clock["now"])

    assert store.hit("s", "k", 1, 60)[0] is True
    assert store.hit("s", "k", 1, 60)[0] is False

    clock["now"] += 61
    assert store.hit("s", "k", 1, 60)[0] is True


def test_scopes_and_keys_are_isolated():
    store = WindowStore()
    assert store.hit("login", "1.2.3.4", 1, 60)[0] is True
    assert store.hit("register", "1.2.3.4", 1, 60)[0] is True
    assert store.hit("login", "5.6.7.8", 1, 60)[0] is True


def test_dependency_raises_429_with_retry_after(monkeypatch):
    # Enabled explicitly: the test suite disables rate limiting globally.
    monkeypatch.setattr(rate_limit_module, "settings", SimpleNamespace(rate_limit_enabled=True))

    dependency = rate_limit(scope="unit-test", limit=1, window_seconds=60, key=lambda request: "fixed")
    request = SimpleNamespace(client=None, headers={})

    dependency(request)

    with pytest.raises(HTTPException) as excinfo:
        dependency(request)

    assert excinfo.value.status_code == 429
    assert excinfo.value.headers["Retry-After"]


def test_dependency_is_disabled_by_settings(client):
    # `client` is requested so the app is imported; RATE_LIMIT_ENABLED=false in tests.
    from app.config import settings

    assert settings.rate_limit_enabled is False