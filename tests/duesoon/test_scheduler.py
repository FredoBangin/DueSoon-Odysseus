from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.reminders.scheduler import ReminderScheduler


class RecordingReminderService:
    def __init__(self) -> None:
        self.calls = 0

    def run_once(self) -> None:
        self.calls += 1


async def test_scheduler_runs_immediately_and_stops_cleanly() -> None:
    service = RecordingReminderService()
    scheduler = ReminderScheduler(service, interval_seconds=3600)

    scheduler.start()
    for _ in range(50):
        if service.calls:
            break
        await asyncio.sleep(0.01)
    await scheduler.stop()

    assert service.calls == 1


async def test_auxiliary_failure_does_not_block_reminder_cycle() -> None:
    service = RecordingReminderService()

    class FailingAuxiliary:
        def run_once(self) -> None:
            raise RuntimeError("integration unavailable")

    scheduler = ReminderScheduler(
        service,
        interval_seconds=3600,
        auxiliary_runners=(FailingAuxiliary(),),
    )

    scheduler.start()
    for _ in range(50):
        if service.calls:
            break
        await asyncio.sleep(0.01)
    await scheduler.stop()

    assert service.calls == 1


def test_application_lifespan_starts_and_stops_injected_scheduler(tmp_path: Path) -> None:
    class RecordingScheduler:
        def __init__(self) -> None:
            self.started = 0
            self.stopped = 0

        def start(self) -> None:
            self.started += 1

        async def stop(self) -> None:
            self.stopped += 1

    scheduler = RecordingScheduler()
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'duesoon.db').as_posix()}",
    )
    app = create_app(settings, reminder_scheduler=scheduler)

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert scheduler.started == 1

    assert scheduler.stopped == 1
