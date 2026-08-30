"""Async lifecycle wrapper for the synchronous reminder service."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol


logger = logging.getLogger(__name__)


class ReminderRunner(Protocol):
    def run_once(self) -> object: ...


class ReminderScheduler:
    """Run reminder evaluation immediately, then at a fixed interval."""

    def __init__(
        self,
        service: ReminderRunner,
        *,
        interval_seconds: int,
        auxiliary_runners: tuple[ReminderRunner, ...] = (),
    ) -> None:
        self._service = service
        self._auxiliary_runners = auxiliary_runners
        self._interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="duesoon-reminders")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        await task
        self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            for runner in self._auxiliary_runners:
                try:
                    await asyncio.to_thread(runner.run_once)
                except Exception:
                    logger.exception("auxiliary scheduler cycle failed")
            try:
                await asyncio.to_thread(self._service.run_once)
            except Exception:
                logger.exception("reminder scheduler cycle failed")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue
