"""OpenAI-compatible chat-completions provider with narrow fallback policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
from threading import RLock
import time
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

import httpx

from .config import EffectiveModelSettings


class ProviderError(RuntimeError):
    """Safe provider failure; message contains no response body or credential."""


class ProviderUnavailable(ProviderError):
    def __init__(self, message: str, *, reason: str = "unavailable", retry_after: float = 30) -> None:
        super().__init__(message)
        self.reason = reason
        self.retry_after = retry_after


class ProviderCooldown(ProviderUnavailable):
    """No provider request was made because an earlier failure opened the circuit."""


class ProviderRejected(ProviderError):
    pass


class InvalidProviderResponse(ProviderError):
    pass


class InputBudgetExceeded(ProviderError):
    pass


@dataclass(frozen=True)
class ProviderAnswer:
    answer: str
    confidence: str
    evidence_ids: tuple[str, ...]
    model: str
    calls_used: int


class ModelProvider(Protocol):
    """Shared bounded contract for assistant answers and structured extraction."""

    def complete(self, settings: EffectiveModelSettings, messages: Sequence[dict[str, str]]) -> ProviderAnswer: ...

    def complete_json(self, settings: EffectiveModelSettings, messages: Sequence[dict[str, str]]) -> dict[str, Any]: ...


@runtime_checkable
class HealthReportingProvider(Protocol):
    def health(self, settings: EffectiveModelSettings) -> dict[str, Any]: ...


ClientFactory = Callable[[float], httpx.Client]


def _default_client_factory(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout_seconds))


class OpenAICompatibleProvider:
    """Calls only `/chat/completions`; never supplies tools or tool credentials."""

    def __init__(
        self, client_factory: ClientFactory | None = None, *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client_factory = client_factory or _default_client_factory
        self._clock, self._wall_clock = clock, wall_clock
        self._lock = RLock()
        self._scope: tuple[Any, ...] | None = None
        self._retry_at = 0.0
        self._reason: str | None = None
        self._verified = False

    def _select_scope(self, settings: EffectiveModelSettings) -> None:
        fingerprint = hashlib.sha256(settings.api_key.get_secret_value().encode()).digest() if settings.api_key else None
        scope = (settings.base_url, fingerprint, settings.primary_model, settings.fallback_models)
        if scope != self._scope:
            self._scope, self._retry_at, self._reason, self._verified = scope, 0.0, None, False

    def health(self, settings: EffectiveModelSettings) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            state = "disabled" if not settings.enabled else "unconfigured" if not settings.configured else "unverified"
            return {"state": state, "reason": "request_in_progress", "retry_after_seconds": 0}
        try:
            self._select_scope(settings)
            remaining = max(0, math.ceil(self._retry_at - self._clock()))
            state = "disabled" if not settings.enabled else "unconfigured" if not settings.configured else (
                "cooldown" if remaining else "healthy" if self._verified else "unverified"
            )
            return {"state": state, "reason": self._reason, "retry_after_seconds": remaining}
        finally:
            self._lock.release()

    def _open_circuit(self, reason: str, seconds: float) -> None:
        self._reason, self._verified = reason, False
        self._retry_at = self._clock() + max(30, min(3600, seconds))

    def _retry_after(self, response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After", "")
        try:
            seconds = float(raw) if raw.isdecimal() else (
                parsedate_to_datetime(raw).astimezone(UTC) - self._wall_clock()
            ).total_seconds()
            return max(30, min(3600, seconds)) if math.isfinite(seconds) else 30
        except (TypeError, ValueError, OverflowError):
            return 30

    def complete(
        self,
        settings: EffectiveModelSettings,
        messages: Sequence[dict[str, str]],
    ) -> ProviderAnswer:
        with self._lock:
            value, model, calls = self._complete_json(settings, messages)
            try:
                return self._parse_value(value, model=model, calls_used=calls)
            except InvalidProviderResponse:
                self._open_circuit("invalid_response", 30)
                raise

    def complete_json(
        self,
        settings: EffectiveModelSettings,
        messages: Sequence[dict[str, str]],
    ) -> dict[str, Any]:
        """Return one validated JSON object for a bounded schema consumer."""

        value, _model, _calls = self._complete_json(settings, messages)
        return value

    def _complete_json(
        self,
        settings: EffectiveModelSettings,
        messages: Sequence[dict[str, str]],
    ) -> tuple[dict[str, Any], str, int]:
        if not settings.configured or not settings.enabled:
            raise ProviderUnavailable("model provider is disabled")
        encoded_size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        # UTF-8 bytes are a conservative tokenizer-independent upper bound.
        if encoded_size > settings.max_input_tokens:
            raise InputBudgetExceeded("assistant input exceeds configured token budget")

        with self._lock:
            self._select_scope(settings)
            if self._retry_at > self._clock():
                raise ProviderCooldown("model provider is cooling down", reason=self._reason or "unavailable")
            try:
                value = self._request_json(settings, messages)
            except ProviderUnavailable as exc:
                self._open_circuit(exc.reason, exc.retry_after)
                raise
            except ProviderRejected:
                self._open_circuit("request_rejected", 300)
                raise
            except InvalidProviderResponse:
                self._open_circuit("invalid_response", 30)
                raise
            self._retry_at, self._reason, self._verified = 0.0, None, True
            return value

    def _request_json(
        self, settings: EffectiveModelSettings, messages: Sequence[dict[str, str]],
    ) -> tuple[dict[str, Any], str, int]:
        models = tuple(dict.fromkeys((settings.primary_model, *settings.fallback_models)))
        ordered = tuple(model for model in models if model)[: settings.call_budget]
        if not ordered:
            raise ProviderUnavailable("no model is configured")

        calls = 0
        last_transient = "model provider unavailable"
        reason, retry_after = "unavailable", 30.0
        with self._client_factory(settings.timeout_seconds) as client:
            for model in ordered:
                calls += 1
                try:
                    response = client.post(
                        f"{settings.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": list(messages),
                            "temperature": 0,
                            "max_tokens": settings.max_output_tokens,
                            "response_format": {"type": "json_object"},
                        },
                    )
                except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                    last_transient = "model provider unavailable"
                    reason = "network_failure"
                    continue

                if response.status_code == 429 or response.status_code >= 500:
                    last_transient = f"model provider transient HTTP {response.status_code}"
                    reason = "rate_limited" if response.status_code == 429 else "server_failure"
                    retry_after = max(retry_after, self._retry_after(response))
                    if response.status_code == 429:
                        try:
                            error = response.json().get("error", {})
                            quota = isinstance(error, dict) and any(error.get(field) in (
                                "insufficient_quota", "quota_exceeded", "billing_hard_limit_reached",
                            ) for field in ("code", "type"))
                        except (AttributeError, TypeError, ValueError):
                            quota = False
                        if quota:
                            raise ProviderUnavailable("model provider quota exhausted", reason="quota_exhausted", retry_after=max(900, retry_after))
                    continue
                if response.status_code < 200 or response.status_code >= 300:
                    raise ProviderRejected(f"model provider rejected request ({response.status_code})")
                return self._parse_json_response(response), model, calls

        raise ProviderUnavailable(last_transient, reason=reason, retry_after=retry_after)

    @staticmethod
    def _parse_json_response(response: httpx.Response) -> dict[str, Any]:
        try:
            payload: Any = response.json()
            content = payload["choices"][0]["message"]["content"]
            value = json.loads(content) if isinstance(content, str) else content
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidProviderResponse("model provider returned invalid structured output") from exc

    @staticmethod
    def _parse_value(
        value: dict[str, Any], *, model: str, calls_used: int
    ) -> ProviderAnswer:
        try:
            answer = value["answer"].strip()
            confidence = value.get("confidence", "unknown")
            evidence_ids = value.get("evidence_ids", [])
            if not answer or confidence not in {"high", "likely", "unknown"}:
                raise ValueError
            if not isinstance(evidence_ids, list) or not all(
                isinstance(item, str) for item in evidence_ids
            ):
                raise ValueError
        except (AttributeError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidProviderResponse("model provider returned invalid structured output") from exc
        return ProviderAnswer(
            answer=answer[:4000],
            confidence=confidence,
            evidence_ids=tuple(evidence_ids[:10]),
            model=model,
            calls_used=calls_used,
        )
