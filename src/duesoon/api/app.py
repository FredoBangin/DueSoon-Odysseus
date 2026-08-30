"""Minimal DueSoon FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from src.duesoon import __version__
from src.duesoon.api.dependencies import require_api_token
from src.duesoon.api.routes.auth import STATIC as WEB_STATIC, router as auth_router
from src.duesoon.api.routes.dashboard import router as dashboard_router
from src.duesoon.api.routes.evidence import router as evidence_router
from src.duesoon.api.schemas import (
    AssignmentResponse,
    CourseResponse,
    NotificationDeliveryResponse,
    SubmissionResponse,
    SyncResponse,
    TestNotificationRequest,
)
from src.duesoon.assistant import (
    AssistantService,
    LearningService,
    ModelAssistantConfig,
    ModelSettingsService,
    OpenAICompatibleProvider,
)
from src.duesoon.assistant.retrieval import AssistantRetrievalService
from src.duesoon.canvas.client import CanvasAPIError, CanvasClient
from src.duesoon.canvas.academic_sync import CanvasAcademicSync
from src.duesoon.canvas.content_sync import CanvasContentSyncService
from src.duesoon.canvas.sync import CanvasSyncService
from src.duesoon.config.settings import DueSoonSettings, get_settings
from src.duesoon.auth.service import AuthService
from src.duesoon.dashboard.assistant import DeterministicAssistant
from src.duesoon.dashboard.briefing import BriefingService
from src.duesoon.diagnostics import DiagnosticsService
from src.duesoon.google import (
    GoogleCalendarEvidenceService,
    GoogleEvidenceService,
    GoogleWorkspaceSyncService,
    GoogleWorkspaceClient,
    GoogleWorkspaceConfig,
)
from src.duesoon.notifications.ntfy import NtfyPublishError, NtfyPublisher
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    database_is_ready,
    session_factory,
)
from src.duesoon.persistence.models import Assignment, Course
from src.duesoon.planning import PlanningService
from src.duesoon.assignments.effective import EffectiveAssignment, project_canvas_assignment
from src.duesoon.intelligence.service import (
    EvidenceInspectionService,
    assignment_load_options,
)
from src.duesoon.intelligence.pipeline import (
    CanvasEvidencePipeline,
    StructuredClaimExtractor,
)
from src.duesoon.intelligence.review import EvidenceReviewService
from src.duesoon.intelligence.identity import ProfessorIdentityService
from src.duesoon.reminders.scheduler import ReminderScheduler
from src.duesoon.reminders.service import ReminderService
from src.duesoon.retained import RetainedToolsService
from src.duesoon.urgency.scoring import score_assignment


ODYSSEUS_STATIC = Path(__file__).resolve().parents[3] / "static"


def create_app(
    settings: DueSoonSettings | None = None,
    *,
    engine: Any | None = None,
    canvas_sync_service: Any | None = None,
    notification_publisher: Any | None = None,
    reminder_scheduler: Any | None = None,
    model_provider: Any | None = None,
    google_client: Any | None = None,
    claim_extractor: Any | None = None,
) -> FastAPI:
    """Create an isolated DueSoon application."""

    runtime_settings = settings or get_settings()
    runtime_engine = engine or create_engine_from_settings(runtime_settings)
    runtime_sessions = session_factory(runtime_engine)
    runtime_model_settings = ModelSettingsService(
        ModelAssistantConfig(environment=runtime_settings.environment),
        runtime_sessions,
    )
    runtime_model_provider = model_provider or OpenAICompatibleProvider()
    runtime_claim_extractor = claim_extractor or StructuredClaimExtractor(
        runtime_model_settings,
        runtime_model_provider,
    )
    runtime_evidence_pipeline = CanvasEvidencePipeline(
        runtime_sessions,
        runtime_claim_extractor,
    )
    owned_canvas_client: CanvasClient | None = None
    runtime_canvas_sync = canvas_sync_service
    if runtime_canvas_sync is None and runtime_settings.canvas_enabled:
        owned_canvas_client = CanvasClient(runtime_settings)
        core_canvas_sync = CanvasSyncService(owned_canvas_client, runtime_sessions)
        runtime_canvas_sync = CanvasAcademicSync(
            core_canvas_sync,
            CanvasContentSyncService(owned_canvas_client, runtime_sessions),
            evidence=runtime_evidence_pipeline,
            evidence_retry_seconds=runtime_settings.evidence_retry_seconds,
            should_extract=lambda: (
                runtime_model_settings.effective().enabled
                and runtime_model_settings.effective().configured
            ),
        )
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
    runtime_auth = AuthService(runtime_settings, runtime_sessions)
    runtime_planning = PlanningService(runtime_sessions)
    runtime_briefing = BriefingService(
        runtime_settings,
        runtime_sessions,
        runtime_planning,
    )
    runtime_diagnostics = DiagnosticsService(runtime_settings, runtime_sessions)
    runtime_evidence = EvidenceInspectionService(runtime_sessions)
    runtime_evidence_review = EvidenceReviewService(runtime_sessions)
    runtime_professors = ProfessorIdentityService(runtime_sessions)
    runtime_learning = LearningService(runtime_sessions)
    runtime_retained = RetainedToolsService(runtime_sessions)
    runtime_google_evidence = GoogleEvidenceService(runtime_sessions)
    runtime_calendar_evidence = GoogleCalendarEvidenceService(runtime_sessions)
    owned_google_client: GoogleWorkspaceClient | None = None
    runtime_google = google_client
    google_config: GoogleWorkspaceConfig | None = None
    if runtime_google is None:
        google_config = GoogleWorkspaceConfig()
        if google_config.enabled:
            owned_google_client = GoogleWorkspaceClient(google_config)
            runtime_google = owned_google_client
    runtime_google_sync = None
    if runtime_google is not None:
        runtime_google_sync = GoogleWorkspaceSyncService(
            runtime_sessions,
            runtime_google,
            runtime_google_evidence,
            runtime_calendar_evidence,
            runtime_evidence_pipeline,
            should_extract=lambda: (
                runtime_model_settings.effective().enabled
                and runtime_model_settings.effective().configured
            ),
            interval_seconds=int(
                getattr(runtime_google.config, "sync_interval_seconds", 900)
            ),
            extraction_retry_seconds=int(
                getattr(runtime_google.config, "extraction_retry_seconds", 3600)
            ),
        )
    runtime_assistant = AssistantService(
        runtime_sessions,
        runtime_model_settings,
        runtime_model_provider,
        deterministic=DeterministicAssistant(),
        learning=runtime_learning,
        retrieval=AssistantRetrievalService(
            runtime_sessions,
            connections={
                "gmail": bool(
                    runtime_google is not None
                    and runtime_google.config.gmail_enabled
                ),
                "google_calendar": bool(
                    runtime_google is not None
                    and runtime_google.config.calendar_enabled
                ),
            },
        ),
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
            settings=runtime_settings,
            planning=runtime_planning,
        )
        runtime_scheduler = ReminderScheduler(
            reminder_service,
            interval_seconds=runtime_settings.scheduler_interval_seconds,
            auxiliary_runners=(runtime_google_sync,) if runtime_google_sync else (),
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
            if owned_google_client is not None:
                owned_google_client.close()
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
    application.state.auth = runtime_auth
    application.state.briefing = runtime_briefing
    application.state.planning = runtime_planning
    application.state.diagnostics = runtime_diagnostics
    application.state.evidence = runtime_evidence
    application.state.evidence_review = runtime_evidence_review
    application.state.professors = runtime_professors
    application.state.assistant = runtime_assistant
    application.state.learning = runtime_learning
    application.state.retained = runtime_retained
    application.state.model_settings = runtime_model_settings
    application.state.google = runtime_google
    application.state.google_evidence = runtime_google_evidence
    application.state.calendar_evidence = runtime_calendar_evidence
    application.state.google_sync = runtime_google_sync
    application.state.evidence_pipeline = runtime_evidence_pipeline
    application.mount("/assets", StaticFiles(directory=WEB_STATIC), name="assets")
    application.mount(
        "/static",
        StaticFiles(directory=ODYSSEUS_STATIC),
        name="odysseus-static",
    )
    application.include_router(auth_router)
    application.include_router(dashboard_router)
    application.include_router(evidence_router)

    @application.middleware("http")
    async def browser_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith(("/app", "/assets", "/api/v1/dashboard", "/api/v1/auth")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

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
                .options(*assignment_load_options())
                .order_by(Assignment.canvas_due_at, Assignment.id)
            ).all()
            effective = tuple(project_canvas_assignment(item) for item in assignments)
            now = datetime.now(UTC)
            return [
                _assignment_response(item, projected, effective, now)
                for item, projected in zip(assignments, effective, strict=True)
            ]

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
            assignments = session.scalars(
                select(Assignment).options(*assignment_load_options()).order_by(Assignment.id)
            ).all()
            effective = tuple(project_canvas_assignment(item) for item in assignments)
            selected = next(
                (
                    (item, projected)
                    for item, projected in zip(assignments, effective, strict=True)
                    if item.id == assignment_id
                ),
                None,
            )
            if selected is None:
                raise HTTPException(status_code=404, detail="assignment not found")
            return _assignment_response(*selected, effective, datetime.now(UTC))

    return application


def _assignment_response(
    assignment: Assignment,
    effective: EffectiveAssignment,
    all_effective: tuple[EffectiveAssignment, ...],
    now: datetime,
) -> AssignmentResponse:
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
        effective_due_at=effective.effective_due_at,
        operational_due_at=effective.operational_due_at,
        deadline_status=effective.deadline_status,
        deadline_confidence=effective.deadline_confidence,
        deadline_source_summary=effective.deadline_source_summary,
        deadline_evidence_ids=list(effective.deadline_evidence_ids),
        due_at_precision=effective.due_at_precision,
        deadline_resolution_explanation=effective.deadline_resolution_explanation,
        conflicting_due_at=list(effective.conflicting_due_at),
        urgency=score_assignment(effective, all_effective, now).to_dict(),
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
