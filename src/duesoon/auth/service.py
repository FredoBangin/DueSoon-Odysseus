"""Persistent single-owner authentication with revocable sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Callable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.auth.passwords import verify_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.models import LoginAttempt, WebSession


class InvalidCredentials(Exception):
    pass


class LoginRateLimited(Exception):
    pass


@dataclass(frozen=True)
class CreatedSession:
    raw_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionPrincipal:
    session_id: int
    username: str
    csrf_token: str
    expires_at: datetime


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class AuthService:
    def __init__(self, settings: DueSoonSettings, sessions: sessionmaker[Session], *,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.settings, self.sessions, self.clock = settings, sessions, clock

    def login(self, username: str, password: str, client_key: str) -> CreatedSession:
        now = _utc(self.clock())
        cutoff = now - timedelta(seconds=self.settings.login_window_seconds)
        safe_key = _digest(client_key)[:64]
        with self.sessions() as session:
            session.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))
            failures = session.scalar(select(func.count(LoginAttempt.id)).where(
                LoginAttempt.client_key == safe_key,
                LoginAttempt.attempted_at >= cutoff,
                LoginAttempt.successful.is_(False),
            )) or 0
            if failures >= self.settings.login_max_attempts:
                session.commit()
                raise LoginRateLimited
            configured = self.settings.owner_password_hash
            valid_name = secrets.compare_digest(username, self.settings.owner_username)
            valid_password = configured is not None and verify_password(
                password, configured.get_secret_value()
            )
            success = bool(valid_name and valid_password)
            session.add(LoginAttempt(client_key=safe_key, attempted_at=now, successful=success))
            if not success:
                session.commit()
                raise InvalidCredentials
            raw_token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            expires_at = now + timedelta(minutes=self.settings.session_ttl_minutes)
            record = WebSession(token_hash=_digest(raw_token), csrf_token=csrf_token,
                                created_at=now, last_seen_at=now, expires_at=expires_at)
            session.add(record)
            session.commit()
            return CreatedSession(raw_token, csrf_token, expires_at)

    def authenticate(self, raw_token: str) -> SessionPrincipal | None:
        if not raw_token:
            return None
        now = _utc(self.clock())
        with self.sessions() as session:
            record = session.scalar(select(WebSession).where(WebSession.token_hash == _digest(raw_token)))
            if record is None or record.revoked_at is not None or _utc(record.expires_at) <= now:
                return None
            record.last_seen_at = now
            session.commit()
            return SessionPrincipal(record.id, self.settings.owner_username,
                                    record.csrf_token, _utc(record.expires_at))

    def revoke(self, raw_token: str) -> None:
        if not raw_token:
            return
        with self.sessions() as session:
            record = session.scalar(select(WebSession).where(WebSession.token_hash == _digest(raw_token)))
            if record is not None:
                record.revoked_at = _utc(self.clock())
                session.commit()
