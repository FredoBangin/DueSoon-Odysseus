"""Audited, idempotent notification orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.ntfy import NtfyPublishError, NtfyPublisher
from src.duesoon.notifications.mirror import DiscordMirrorService
from src.duesoon.persistence.models import NotificationDelivery, utc_now


logger = logging.getLogger(__name__)


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
        *,
        discord_mirror: DiscordMirrorService | None = None,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._publisher = publisher
        self._discord_mirror = discord_mirror

    def send_test(
        self,
        *,
        idempotency_key: str,
        title: str,
        message: str,
        priority: int,
    ) -> DeliveryResult:
        result = self._send(
            idempotency_key=idempotency_key,
            notification_kind="controlled_test",
            title=title,
            message=message,
            priority=priority,
            tags=["white_check_mark"],
        )
        self._mirror(result, assignment_deadlines={}, expires_at=None)
        return result

    def send_reminder(
        self,
        *,
        idempotency_key: str,
        title: str,
        message: str,
        priority: int,
        notification_kind: str = "deadline_checkpoint",
        assignment_deadlines: dict[int, datetime] | None = None,
        expires_at: datetime | None = None,
    ) -> DeliveryResult:
        result = self._send(
            idempotency_key=idempotency_key,
            notification_kind=notification_kind,
            title=title,
            message=message,
            priority=priority,
            tags=["warning" if notification_kind.startswith("adaptive") else "alarm_clock"],
        )
        self._mirror(result, assignment_deadlines=assignment_deadlines or {}, expires_at=expires_at)
        return result

    def _mirror(self, result: DeliveryResult, *, assignment_deadlines: dict[int, datetime], expires_at: datetime | None) -> None:
        if self._discord_mirror is not None and result.status in {"sent", "dry_run"}:
            self._discord_mirror.enqueue(result.delivery_id, assignment_deadlines=assignment_deadlines, expires_at=expires_at)

    def retry_pending(self) -> None:
        if self._discord_mirror is not None:
            try:
                self._discord_mirror.run_once()
            except Exception:
                logger.error("Discord retry cycle failed; primary reminder evaluation continues")

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
            if existing is not None and existing.status != "retry_scheduled":
                return self._existing_result(existing)

            if existing is not None:
                delivery = existing
                delivery.status = "pending"
                delivery.error_code = None
                delivery.attempted_at = utc_now()
                delivery.completed_at = None
                session.commit()
            else:
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
                delivery.status = (
                    "unknown"
                    if exc.ambiguous
                    else "retry_scheduled" if exc.retryable else "failed"
                )
                delivery.error_code = (
                    "ambiguous_outcome"
                    if exc.ambiguous
                    else "provider_transient" if exc.retryable else "provider_error"
                )
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
