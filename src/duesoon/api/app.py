"""Minimal DueSoon FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
import secrets
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.duesoon import __version__
from src.duesoon.api.schemas import (
    AssignmentResponse,
    CourseResponse,
    NotificationDeliveryResponse,
    SubmissionResponse,
    SyncResponse,
    TestNotificationRequest,
)
from src.duesoon.canvas.client import CanvasAPIError, CanvasClient
from src.duesoon.canvas.sync import CanvasSyncService
from src.duesoon.config.settings import DueSoonSettings, get_settings
from src.duesoon.notifications.ntfy import NtfyPublishError, NtfyPublisher
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    database_is_ready,
    session_factory,
)
from src.duesoon.persistence.models import Assignment, Course
from src.duesoon.reminders.scheduler import ReminderScheduler
from src.duesoon.reminders.service import ReminderService


def create_app(
    settings: DueSoonSettings | None = None,
    *,
    engine: Any | None = None,
    canvas_sync_service: Any | None = None,
    notification_publisher: Any | None = None,
    reminder_scheduler: Any | None = None,
) -> FastAPI:
    """Create an isolated DueSoon application."""

    runtime_settings = settings or get_settings()
    runtime_engine = engine or create_engine_from_settings(runtime_settings)
    runtime_sessions = session_factory(runtime_engine)
    owned_canvas_client: CanvasClient | None = None
    runtime_canvas_sync = canvas_sync_service
    if runtime_canvas_sync is None and runtime_settings.canvas_enabled:
        owned_canvas_client = CanvasClient(runtime_settings)
        runtime_canvas_sync = CanvasSyncService(owned_canvas_client, runtime_sessions)
    owned_notification_publisher: NtfyPublisher | None = None
    runtime_notification_publisher = notification_publisher
    if runtime_notification_publisher is None and runtime_settings.ntfy_enabled:
        owned_notification_publisher = NtfyPublisher(runtime_settings)
        runtime_notification_publisher = owned_notification_publisher
    runtime_notifications = NotificationService(
        runtime_settings,
        runtime_sessions,
        runtime_notification_publisher,
    )
    runtime_scheduler = reminder_scheduler
    if (
        runtime_scheduler is None
        and runtime_settings.scheduler_enabled
        and runtime_canvas_sync is not None
    ):
        reminder_service = ReminderService(
            runtime_sessions,
            runtime_canvas_sync,
            runtime_notifications,
        )
        runtime_scheduler = ReminderScheduler(
            reminder_service,
            interval_seconds=runtime_settings.scheduler_interval_seconds,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            create_schema(runtime_engine)
        except Exception:
            pass
        if runtime_scheduler is not None:
            runtime_scheduler.start()
        try:
            yield
        finally:
            if runtime_scheduler is not None:
                await runtime_scheduler.stop()
            if owned_canvas_client is not None:
                owned_canvas_client.close()
            if owned_notification_publisher is not None:
                owned_notification_publisher.close()
            runtime_engine.dispose()

    application = FastAPI(
        title="DueSoon API",
        version=__version__,
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.state.engine = runtime_engine
    application.state.sessions = runtime_sessions
    application.state.canvas_sync = runtime_canvas_sync
    application.state.notifications = runtime_notifications
    application.state.reminder_scheduler = runtime_scheduler

    @application.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok", "service": "duesoon"}

    @application.get("/health/ready", tags=["health"])
    def readiness() -> dict[str, str]:
        if not database_is_ready(runtime_engine):
            raise HTTPException(status_code=503, detail="database unavailable")
        return {"status": "ready", "database": "ready"}

    @application.get("/api/v1/system/info", tags=["system"])
    def system_info() -> dict[str, str | bool]:
        return {
            "service": "duesoon",
            "version": __version__,
            "environment": runtime_settings.environment,
            "dry_run": runtime_settings.dry_run,
            "scheduler_enabled": runtime_settings.scheduler_enabled,
            "notification_provider": "ntfy" if runtime_settings.ntfy_enabled else "disabled",
        }

    def require_api_token(x_api_token: str | None = Header(default=None)) -> None:
        configured = runtime_settings.api_token
        if configured is None:
            return
        if x_api_token is None or not secrets.compare_digest(
            x_api_token, configured.get_secret_value()
        ):
            raise HTTPException(status_code=401, detail="invalid API token")

    @application.post(
        "/api/v1/canvas/sync",
        response_model=SyncResponse,
        tags=["canvas"],
    )
    def sync_canvas(_authorization: None = Depends(require_api_token)) -> SyncResponse:
        if not runtime_settings.canvas_enabled or runtime_canvas_sync is None:
            raise HTTPException(status_code=409, detail="Canvas ingestion is disabled")
        try:
            summary = runtime_canvas_sync.sync()
        except CanvasAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return SyncResponse(**summary.to_dict())

    @application.post(
        "/api/v1/notifications/test",
        response_model=NotificationDeliveryResponse,
        tags=["notifications"],
    )
    def send_test_notification(
        request: TestNotificationRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=255),
        _authorization: None = Depends(require_api_token),
    ) -> NotificationDeliveryResponse:
        if not runtime_settings.dry_run and not runtime_settings.ntfy_enabled:
            raise HTTPException(status_code=409, detail="ntfy delivery is disabled")
        try:
            result = runtime_notifications.send_test(
                idempotency_key=idempotency_key,
                title=request.title,
                message=request.message,
                priority=request.priority,
            )
        except NtfyPublishError as exc:
            status_code = 409 if str(exc) == "ntfy delivery is disabled" else 502
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return NotificationDeliveryResponse(
            status=result.status,
            delivery_id=result.delivery_id,
            provider_message_id=result.provider_message_id,
        )

    @application.get(
        "/api/v1/courses",
        response_model=list[CourseResponse],
        tags=["academic"],
    )
    def list_courses(_authorization: None = Depends(require_api_token)) -> list[CourseResponse]:
        with runtime_sessions() as session:
            courses = session.scalars(select(Course).order_by(Course.name, Course.id)).all()
            return [
                CourseResponse(
                    id=course.id,
                    canvas_course_id=course.canvas_course_id,
                    name=course.name,
                    course_code=course.course_code,
                    term=course.term,
                    timezone=course.timezone,
                    active=course.active,
                )
                for course in courses
            ]

    @application.get(
        "/api/v1/assignments",
        response_model=list[AssignmentResponse],
        tags=["academic"],
    )
    def list_assignments(
        _authorization: None = Depends(require_api_token),
    ) -> list[AssignmentResponse]:
        with runtime_sessions() as session:
            assignments = session.scalars(
                select(Assignment)
                .options(selectinload(Assignment.course), selectinload(Assignment.submission))
                .order_by(Assignment.canvas_due_at, Assignment.id)
            ).all()
            return [_assignment_response(item) for item in assignments]

    @application.get(
        "/api/v1/assignments/{assignment_id}",
        response_model=AssignmentResponse,
        tags=["academic"],
    )
    def assignment_detail(
        assignment_id: int,
        _authorization: None = Depends(require_api_token),
    ) -> AssignmentResponse:
        with runtime_sessions() as session:
            assignment = session.scalar(
                select(Assignment)
                .where(Assignment.id == assignment_id)
                .options(selectinload(Assignment.course), selectinload(Assignment.submission))
            )
            if assignment is None:
                raise HTTPException(status_code=404, detail="assignment not found")
            return _assignment_response(assignment)

    return application


def _assignment_response(assignment: Assignment) -> AssignmentResponse:
    submission = assignment.submission
    return AssignmentResponse(
        id=assignment.id,
        canvas_assignment_id=assignment.canvas_assignment_id,
        course_id=assignment.course_id,
        canvas_course_id=assignment.course.canvas_course_id,
        course_name=assignment.course.name,
        canonical_title=assignment.canonical_title,
        canvas_due_at=assignment.canvas_due_at,
        unlock_at=assignment.unlock_at,
        lock_at=assignment.lock_at,
        points_possible=assignment.points_possible,
        assignment_type=assignment.assignment_type,
        submission_types=assignment.submission_types,
        grading_type=assignment.grading_type,
        html_url=assignment.html_url,
        published=assignment.published,
        submission=(
            SubmissionResponse(
                normalized_status=submission.normalized_status,
                raw_status=submission.raw_status,
                submitted_at=submission.submitted_at,
                graded_at=submission.graded_at,
                missing=submission.missing,
                late=submission.late,
            )
            if submission is not None
            else None
        ),
    )


app = create_app()
