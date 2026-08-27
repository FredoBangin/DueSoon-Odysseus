from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.duesoon.api.app import create_app
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.ntfy import PublishResult
from src.duesoon.persistence.database import create_engine_from_settings, session_factory
from src.duesoon.persistence.models import NotificationDelivery


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish(self, **payload: object) -> PublishResult:
        self.calls.append(payload)
        return PublishResult(provider_message_id="provider-message-1")

    def close(self) -> None:
        pass


def build_settings(tmp_path: Path, **overrides: object) -> DueSoonSettings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": f"sqlite:///{(tmp_path / 'notifications.db').as_posix()}",
        "api_token": "api-secret",
    }
    values.update(overrides)
    return DueSoonSettings(_env_file=None, **values)


def notification_request(client: TestClient, *, key: str = "test-delivery-1"):
    return client.post(
        "/api/v1/notifications/test",
        headers={"X-API-Token": "api-secret", "Idempotency-Key": key},
        json={
            "title": "DueSoon is live",
            "message": "Azure delivery reached ntfy.",
            "priority": 4,
        },
    )


def test_live_notification_is_token_guarded_audited_and_deduplicated(tmp_path: Path) -> None:
    settings = build_settings(
        tmp_path,
        dry_run=False,
        ntfy_enabled=True,
        ntfy_url="https://notify.example.test",
        ntfy_topic="private-topic",
        ntfy_token="ntfy-token",
    )
    engine = create_engine_from_settings(settings)
    publisher = FakePublisher()
    app = create_app(settings, engine=engine, notification_publisher=publisher)

    with TestClient(app) as client:
        unauthorized = client.post(
            "/api/v1/notifications/test",
            headers={"Idempotency-Key": "unauthorized"},
            json={"title": "x", "message": "y", "priority": 3},
        )
        first = notification_request(client)
        duplicate = notification_request(client)

    assert unauthorized.status_code == 401
    assert first.status_code == 200
    assert first.json() == {
        "status": "sent",
        "delivery_id": 1,
        "provider_message_id": "provider-message-1",
    }
    assert duplicate.status_code == 200
    assert duplicate.json() == {
        "status": "already_sent",
        "delivery_id": 1,
        "provider_message_id": "provider-message-1",
    }
    assert len(publisher.calls) == 1

    with session_factory(engine)() as session:
        deliveries = session.scalars(select(NotificationDelivery)).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "sent"
        assert deliveries[0].provider_message_id == "provider-message-1"


def test_dry_run_is_audited_without_contacting_ntfy(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, dry_run=True)
    engine = create_engine_from_settings(settings)
    publisher = FakePublisher()
    app = create_app(settings, engine=engine, notification_publisher=publisher)

    with TestClient(app) as client:
        response = notification_request(client, key="dry-run-1")

    assert response.status_code == 200
    assert response.json() == {
        "status": "dry_run",
        "delivery_id": 1,
        "provider_message_id": None,
    }
    assert publisher.calls == []

    with session_factory(engine)() as session:
        delivery = session.scalar(select(NotificationDelivery))
        assert delivery is not None
        assert delivery.status == "dry_run"


def test_live_notification_requires_enabled_provider(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, dry_run=False)

    with TestClient(create_app(settings)) as client:
        response = notification_request(client, key="provider-disabled")

    assert response.status_code == 409
    assert response.json() == {"detail": "ntfy delivery is disabled"}
