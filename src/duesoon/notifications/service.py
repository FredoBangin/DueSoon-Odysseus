"""Audited, idempotent notification orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.ntfy import NtfyPublishError, NtfyPublisher
from src.duesoon.persistence.models import NotificationDelivery, utc_now


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    delivery_id: int
    provider_message_id: str | None


class NotificationService:
    """Persist delivery intent before calling the provider."""

    def __init__(
        self,
        settings: DueSoonSettings,
        sessions: sessionmaker[Session],
        publisher: NtfyPublisher | None,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._publisher = publisher

    def send_test(
        self,
        *,
        idempotency_key: str,
        title: str,
        message: str,
        priority: int,
    ) -> DeliveryResult:
        return self._send(
            idempotency_key=idempotency_key,
            notification_kind="controlled_test",
            title=title,
            message=message,
            priority=priority,
            tags=["white_check_mark"],
        )

    def send_reminder(
        self,
        *,
        idempotency_key: str,
        title: str,
        message: str,
        priority: int,
        notification_kind: str = "deadline_checkpoint",
    ) -> DeliveryResult:
        return self._send(
            idempotency_key=idempotency_key,
            notification_kind=notification_kind,
            title=title,
            message=message,
            priority=priority,
            tags=["warning" if notification_kind.startswith("adaptive") else "alarm_clock"],
        )

    def _send(
        self,
        *,
        idempotency_key: str,
        notification_kind: str,
        title: str,
        message: str,
        priority: int,
        tags: list[str],
    ) -> DeliveryResult:
        with self._sessions() as session:
            existing = session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.dedup_key == idempotency_key
                )
            )
            if existing is not None:
                return self._existing_result(existing)

            delivery = NotificationDelivery(
                dedup_key=idempotency_key,
                notification_kind=notification_kind,
                status="pending",
                rendered_title=title,
                rendered_body=message,
                priority=priority,
                provider="ntfy",
                attempted_at=utc_now(),
            )
            session.add(delivery)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(NotificationDelivery).where(
                        NotificationDelivery.dedup_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                return self._existing_result(existing)

            if self._settings.dry_run:
                delivery.status = "dry_run"
                delivery.completed_at = utc_now()
                session.commit()
                return self._result(delivery)

            if not self._settings.ntfy_enabled or self._publisher is None:
                delivery.status = "failed"
                delivery.error_code = "provider_disabled"
                delivery.completed_at = utc_now()
                session.commit()
                raise NtfyPublishError("ntfy delivery is disabled")

            try:
                published = self._publisher.publish(
                    title=title,
                    message=message,
                    priority=priority,
                    tags=tags,
                )
            except NtfyPublishError as exc:
                delivery.status = "unknown" if exc.ambiguous else "failed"
                delivery.error_code = "ambiguous_timeout" if exc.ambiguous else "provider_error"
                delivery.completed_at = utc_now()
                session.commit()
                raise

            delivery.status = "sent"
            delivery.provider_message_id = published.provider_message_id
            delivery.completed_at = utc_now()
            session.commit()
            return self._result(delivery)

    @staticmethod
    def _result(delivery: NotificationDelivery) -> DeliveryResult:
        return DeliveryResult(
            status=delivery.status,
            delivery_id=delivery.id,
            provider_message_id=delivery.provider_message_id,
        )

    @classmethod
    def _existing_result(cls, delivery: NotificationDelivery) -> DeliveryResult:
        result = cls._result(delivery)
        return DeliveryResult(
            status=f"already_{result.status}",
            delivery_id=result.delivery_id,
            provider_message_id=result.provider_message_id,
        )
