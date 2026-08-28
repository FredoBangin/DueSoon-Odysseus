"""OpenAI-compatible chat-completions provider with narrow fallback policy."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Sequence

import httpx

from .config import EffectiveModelSettings


class ProviderError(RuntimeError):
    """Safe provider failure; message contains no response body or credential."""


class ProviderUnavailable(ProviderError):
    pass


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


ClientFactory = Callable[[float], httpx.Client]


def _default_client_factory(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout_seconds))


class OpenAICompatibleProvider:
    """Calls only `/chat/completions`; never supplies tools or tool credentials."""

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or _default_client_factory

    def complete(
        self,
        settings: EffectiveModelSettings,
        messages: Sequence[dict[str, str]],
    ) -> ProviderAnswer:
        if not settings.configured or not settings.enabled:
            raise ProviderUnavailable("model provider is disabled")
        encoded_size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        # UTF-8 bytes are a conservative tokenizer-independent upper bound.
        if encoded_size > settings.max_input_tokens:
            raise InputBudgetExceeded("assistant input exceeds configured token budget")

        models = (settings.primary_model, *settings.fallback_models)
        ordered = tuple(model for model in models if model)[: settings.call_budget]
        if not ordered:
            raise ProviderUnavailable("no model is configured")

        calls = 0
        last_transient = "model provider unavailable"
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
                    continue

                if response.status_code == 429 or response.status_code >= 500:
                    last_transient = f"model provider transient HTTP {response.status_code}"
                    continue
                if response.status_code < 200 or response.status_code >= 300:
                    raise ProviderRejected(f"model provider rejected request ({response.status_code})")
                return self._parse_response(response, model=model, calls_used=calls)

        raise ProviderUnavailable(last_transient)

    @staticmethod
    def _parse_response(
        response: httpx.Response, *, model: str, calls_used: int
    ) -> ProviderAnswer:
        try:
            payload: Any = response.json()
            content = payload["choices"][0]["message"]["content"]
            value = json.loads(content) if isinstance(content, str) else content
            answer = value["answer"].strip()
            confidence = value.get("confidence", "unknown")
            evidence_ids = value.get("evidence_ids", [])
            if not answer or confidence not in {"high", "likely", "unknown"}:
                raise ValueError
            if not isinstance(evidence_ids, list) or not all(
                isinstance(item, str) for item in evidence_ids
            ):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidProviderResponse("model provider returned invalid structured output") from exc
        return ProviderAnswer(
            answer=answer[:4000],
            confidence=confidence,
            evidence_ids=tuple(evidence_ids[:10]),
            model=model,
            calls_used=calls_used,
        )
