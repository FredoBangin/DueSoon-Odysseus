from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runtime_requirements_are_foundation_only() -> None:
    requirements = {
        line.strip()
        for line in read("requirements.txt").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert requirements == {
        "fastapi==0.141.1",
        "pydantic-settings==2.15.0",
        "SQLAlchemy==2.0.52",
        "uvicorn==0.52.4",
    }


def test_active_manifests_exclude_odysseus_tooling() -> None:
    active_text = "\n".join(
        (
            read("requirements.txt"),
            read("Dockerfile"),
            read("docker-compose.yml"),
            read(".env.example"),
        )
    ).lower()
    forbidden = (
        "chromadb",
        "searxng",
        "realesrgan",
        "faster-whisper",
        "youtube",
        "mcp",
        "openssh",
        "chromium",
        "nodejs",
        "docker.sock",
        "llm_host",
        "openai_api_key",
    )

    assert [token for token in forbidden if token in active_text] == []


def test_dockerfile_runs_only_due_soon_as_non_root() -> None:
    dockerfile = read("Dockerfile")

    assert "USER duesoon" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "src.duesoon.api.app:app" in dockerfile
    assert "app:app" not in dockerfile.replace("src.duesoon.api.app:app", "")


def test_compose_contains_only_due_soon_and_ntfy_services() -> None:
    compose = read("docker-compose.yml")

    assert "  duesoon:" in compose
    assert "  ntfy:" in compose
    assert "  odysseus:" not in compose
    assert "DUESOON_DATABASE_URL" in compose
    assert "NTFY_AUTH_DEFAULT_ACCESS=deny-all" in compose


def test_gpu_overlays_are_removed() -> None:
    assert not (ROOT / "docker-compose.gpu-amd.yml").exists()
    assert not (ROOT / "docker-compose.gpu-nvidia.yml").exists()


def test_default_pytest_scope_is_due_soon_only() -> None:
    pyproject = read("pyproject.toml")
    conftest = read("tests/conftest.py")

    assert 'testpaths = ["tests/duesoon"]' in pyproject
    assert "core.database" not in conftest
    assert "src.database" not in conftest
