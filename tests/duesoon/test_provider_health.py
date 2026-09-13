from dataclasses import replace
from datetime import UTC, datetime
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
from pydantic import SecretStr
import pytest

from src.duesoon.assistant.config import EffectiveModelSettings
from src.duesoon.assistant.provider import (
    InvalidProviderResponse, OpenAICompatibleProvider, ProviderCooldown,
    ProviderRejected, ProviderUnavailable,
)


def settings():
    return EffectiveModelSettings(
        enabled=True, base_url="https://models.example/v1", api_key=SecretStr("private-test-key"),
        primary_model="primary", fallback_models=("backup", "primary", "backup"),
        timeout_seconds=3, max_input_tokens=1000, max_output_tokens=100, call_budget=5,
    )


MESSAGES = [{"role": "user", "content": "Untrusted private test text"}]


def success(value=None):
    value = value or {"answer": "Verified", "confidence": "likely", "evidence_ids": []}
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})


def provider(handler, now):
    return OpenAICompatibleProvider(
        lambda timeout: httpx.Client(timeout=timeout, transport=httpx.MockTransport(handler)),
        clock=lambda: now[0], wall_clock=lambda: datetime(2026, 9, 13, tzinfo=UTC),
    )


def test_quota_failure_stops_fallback_and_shares_circuit_with_extraction():
    calls, now = [], [100.0]

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": {"code": "insufficient_quota", "message": "private billing details"}})

    service = provider(handler, now)
    assert service.health(settings())["state"] == "unverified"
    with pytest.raises(ProviderUnavailable, match="quota exhausted"):
        service.complete(settings(), MESSAGES)
    with pytest.raises(ProviderCooldown):
        service.complete_json(settings(), MESSAGES)
    assert len(calls) == 1
    assert service.health(settings()) == {"state": "cooldown", "reason": "quota_exhausted", "retry_after_seconds": 900}
    assert "private" not in str(service.health(settings()))


@pytest.mark.parametrize("retry_after,expected", [("120", 120), ("Sun, 13 Sep 2026 00:02:00 GMT", 120), ("999999", 3600), ("invalid", 30), ("0", 30)])
def test_retry_after_is_bounded_and_recovery_is_verified(retry_after, expected):
    calls, now = [], [100.0]

    def handler(request):
        calls.append(json.loads(request.content)["model"])
        return httpx.Response(429, headers={"Retry-After": retry_after}) if len(calls) <= 2 else success()

    service = provider(handler, now)
    with pytest.raises(ProviderUnavailable):
        service.complete(settings(), MESSAGES)
    assert calls == ["primary", "backup"], "Duplicate fallback models must not consume calls"
    assert service.health(settings())["retry_after_seconds"] == expected
    with pytest.raises(ProviderCooldown):
        service.complete(settings(), MESSAGES)
    now[0] += expected
    assert service.health(settings())["state"] == "unverified"
    assert service.complete(settings(), MESSAGES).answer == "Verified"
    assert service.health(settings()) == {"state": "healthy", "reason": None, "retry_after_seconds": 0}


def test_auth_rejection_cools_down_but_changed_credential_can_recover():
    calls, now = [], [100.0]

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="private response") if len(calls) == 1 else success()

    service = provider(handler, now)
    with pytest.raises(ProviderRejected, match=r"\(401\)"):
        service.complete(settings(), MESSAGES)
    with pytest.raises(ProviderCooldown):
        service.complete(settings(), MESSAGES)
    assert len(calls) == 1
    changed = replace(settings(), api_key=SecretStr("replacement-test-key"))
    assert service.health(changed)["state"] == "unverified"
    assert service.complete(changed, MESSAGES).calls_used == 1


def test_network_failure_opens_shared_circuit_without_sleeping():
    calls, now = [], [100.0]

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private transport details", request=request)

    service = provider(handler, now)
    with pytest.raises(ProviderUnavailable):
        service.complete_json(settings(), MESSAGES)
    with pytest.raises(ProviderCooldown):
        service.complete(settings(), MESSAGES)
    assert len(calls) == 2
    assert service.health(settings())["reason"] == "network_failure"


@pytest.mark.parametrize("response", [httpx.Response(200, json={"unexpected": "private"}), success({"answer": [], "confidence": "high"})])
def test_invalid_response_is_safe_and_not_repeated(response):
    now = [100.0]
    service = provider(lambda request: response, now)
    with pytest.raises(InvalidProviderResponse):
        service.complete(settings(), MESSAGES)
    assert service.health(settings())["reason"] == "invalid_response"
    with pytest.raises(ProviderCooldown):
        service.complete_json(settings(), MESSAGES)


def test_disabled_and_unconfigured_health_do_not_claim_reachability():
    service = provider(lambda request: success(), [100.0])
    assert service.health(replace(settings(), enabled=False))["state"] == "disabled"
    assert service.health(replace(settings(), api_key=None))["state"] == "unconfigured"


def test_concurrent_workflows_share_one_failure_chain():
    first_started, second_started, release = Event(), Event(), Event()
    calls = []

    def handler(request):
        calls.append(request)
        first_started.set()
        assert release.wait(2)
        return httpx.Response(503)

    service = provider(handler, [100.0])

    def run(second=False):
        if second:
            second_started.set()
        try:
            service.complete_json(settings(), MESSAGES)
        except ProviderUnavailable as exc:
            return type(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run)
        assert first_started.wait(2)
        assert service.health(settings())["reason"] == "request_in_progress", "Health reads must not block behind provider network calls"
        second = executor.submit(run, True)
        assert second_started.wait(2)
        release.set()
        assert first.result(timeout=3) is ProviderUnavailable
        assert second.result(timeout=3) is ProviderCooldown
    assert len(calls) == 2


def test_model_settings_exposes_health_without_provider_secret(tmp_path):
    from src.duesoon.assistant.config import ModelAssistantConfig
    from src.duesoon.assistant.service import ModelSettingsService
    from src.duesoon.config.settings import DueSoonSettings
    from src.duesoon.persistence.database import create_engine_from_settings, create_schema, session_factory

    engine = create_engine_from_settings(DueSoonSettings(_env_file=None, environment="test", database_url=f"sqlite:///{tmp_path / 'health.db'}"))
    create_schema(engine)
    service = provider(lambda request: success(), [100.0])
    config = ModelAssistantConfig(_env_file=None, enabled=True, api_key=SecretStr("private-test-key"), primary_model="primary")
    model = ModelSettingsService(config, session_factory(engine), service)
    assert model.status()["provider_health"]["state"] == "unverified"
    service.complete(model.effective(), MESSAGES)
    value = model.status()
    assert value["provider_health"]["state"] == "healthy"
    assert "private-test-key" not in json.dumps(value)
    engine.dispose()
