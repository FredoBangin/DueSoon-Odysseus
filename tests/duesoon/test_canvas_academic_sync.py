from __future__ import annotations

from dataclasses import dataclass

from src.duesoon.canvas.academic_sync import CanvasAcademicSync


@dataclass(frozen=True)
class Summary:
    name: str

    def to_dict(self):
        return {"name": self.name}


class Core:
    def __init__(self) -> None:
        self.calls = 0

    def sync(self):
        self.calls += 1
        return Summary("core")


class Content:
    def __init__(self) -> None:
        self.calls = 0

    def sync(self):
        self.calls += 1
        return Summary("content")


class Evidence:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def process_pending(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("optional extraction failed")
        return Summary("evidence")


def test_academic_sync_processes_pending_evidence_after_content() -> None:
    core, content, evidence = Core(), Content(), Evidence()
    service = CanvasAcademicSync(core, content, evidence=evidence)

    result = service.sync()

    assert result.name == "core"
    assert core.calls == content.calls == evidence.calls == 1
    assert service.last_evidence_summary == {"name": "evidence"}


def test_optional_evidence_failure_never_stops_core_sync() -> None:
    core, content, evidence = Core(), Content(), Evidence(fail=True)
    service = CanvasAcademicSync(core, content, evidence=evidence)

    result = service.sync()

    assert result.name == "core"
    assert service.last_evidence_summary == {"status": "failed_backoff"}


def test_failed_evidence_waits_for_backoff_while_core_sync_continues() -> None:
    current = [0.0]
    core, content, evidence = Core(), Content(), Evidence(fail=True)
    service = CanvasAcademicSync(
        core,
        content,
        evidence=evidence,
        content_interval_seconds=1800,
        evidence_retry_seconds=3600,
        monotonic=lambda: current[0],
    )

    service.sync()
    current[0] = 1801
    service.sync()
    current[0] = 3601
    service.sync()

    assert core.calls == 3
    assert content.calls == 3
    assert evidence.calls == 2


def test_disabled_model_extraction_does_not_call_evidence_pipeline() -> None:
    core, content, evidence = Core(), Content(), Evidence()
    service = CanvasAcademicSync(
        core,
        content,
        evidence=evidence,
        should_extract=lambda: False,
    )

    service.sync()

    assert core.calls == content.calls == 1
    assert evidence.calls == 0
    assert service.last_evidence_summary == {"status": "disabled"}
