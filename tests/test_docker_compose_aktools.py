"""Compose contract for the local AKTools HTTP sidecar."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
AKTOOLS_DOCKERFILE = ROOT / "docker" / "aktools.Dockerfile"
AKTOOLS_PATCH = ROOT / "docker" / "aktools_sitecustomize.py"


@pytest.mark.unit
def test_aktools_compose_builds_upgraded_sidecar():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    dockerfile = AKTOOLS_DOCKERFILE.read_text(encoding="utf-8")
    patch = AKTOOLS_PATCH.read_text(encoding="utf-8")
    assert "dockerfile: aktools.Dockerfile" in compose
    assert "image: tradingagents-aktools:local" in compose
    assert 'image: registry.cn-shanghai.aliyuncs.com/akfamily/aktools:1.8.95' not in compose
    assert '"akshare>=1.16"' in dockerfile
    assert '"aktools>=0.0.89"' in dockerfile
    assert '"fastapi>=0.115.5,<0.116"' in dockerfile
    assert '"starlette>=0.40,<1"' in dockerfile
    assert "PYTHONPATH=/opt/aktools-patch" in dockerfile
    assert "get_latest_version" in patch
    assert '"-m", "aktools"' in dockerfile
    assert "http://127.0.0.1:8080/docs" in compose
    assert "AKSHARE_BASE_URL: http://aktools:8080" in compose
