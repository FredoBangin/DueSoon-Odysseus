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
        "httpx==0.28.1",
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
    assert "DUESOON_CANVAS_ENABLED" in compose
    assert "DUESOON_CANVAS_BASE_URL" in compose
    assert "DUESOON_CANVAS_ACCESS_TOKEN" in compose
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


def test_azure_compose_exposes_only_caddy_and_persists_managed_disk_state() -> None:
    compose = read("deploy/azure/docker-compose.production.yml")

    assert compose.count("ports:") == 1
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "DUESOON_SCHEDULER_WORKERS=1" in compose
    assert "/mnt/duesoon/app:/app/data" in compose
    assert "/mnt/duesoon/ntfy-cache:/var/cache/ntfy" in compose
    assert "/mnt/duesoon/ntfy-data:/var/lib/ntfy" in compose
    assert "NTFY_AUTH_DEFAULT_ACCESS=deny-all" in compose
    assert "NTFY_UPSTREAM_BASE_URL=https://ntfy.sh" in compose


def test_azure_caddy_routes_due_soon_api_and_ntfy_over_one_https_host() -> None:
    caddyfile = read("deploy/azure/Caddyfile")

    assert "{$DUESOON_PUBLIC_HOST}" in caddyfile
    assert "reverse_proxy duesoon:7000" in caddyfile
    assert "reverse_proxy ntfy:80" in caddyfile
    assert "header Strict-Transport-Security" in caddyfile
    assert "@duesoon path / /login /app /app/* /assets/* /api/* /health/*" in caddyfile
    assert "Content-Security-Policy" in caddyfile
    assert caddyfile.index("handle @duesoon") < caddyfile.index("reverse_proxy ntfy:80")


def test_cloud_init_mounts_lun_zero_before_starting_compose() -> None:
    cloud_init = read("deploy/azure/cloud-init.yml")

    assert "/dev/disk/azure/scsi1/lun0" in cloud_init
    assert "/mnt/duesoon" in cloud_init
    assert "docker.io" in cloud_init
    assert "docker-compose-v2" in cloud_init
