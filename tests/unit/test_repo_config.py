"""Validação de YAML de workflows e exemplos de docker compose."""

import shutil
import subprocess

import pytest
import yaml

from conftest import REPO_ROOT

WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
COMPOSE_FILES = sorted((REPO_ROOT / "examples" / "compose").glob("docker-compose*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid_yaml(path):
    data = yaml.safe_load(path.read_text())
    assert "jobs" in data and data["jobs"], f"{path.name} sem jobs"


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_compose_is_valid_yaml(path):
    data = yaml.safe_load(path.read_text())
    assert data.get("services"), f"{path.name} sem services"
    assert "version" not in data, "o campo 'version' é obsoleto no Compose Spec"


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_compose_uses_published_image(path):
    data = yaml.safe_load(path.read_text())
    for name, svc in data["services"].items():
        if "rpa" in name:
            assert svc.get("image", "").startswith("ghcr.io/nailtongomes/rpa-worker-selenium"), name


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _docker_compose_available(), reason="docker compose indisponível")
@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_compose_config(path):
    """Validação oficial do Compose (interpolação, tipos, chaves)."""
    env = {"SCRIPT_URL": "https://example.com/x.py", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    result = subprocess.run(
        ["docker", "compose", "-f", str(path), "config", "--quiet"],
        capture_output=True, text=True, cwd=path.parent, env=env,
    )
    assert result.returncode == 0, result.stderr


def test_caddyfile_is_present_for_caddy_example():
    caddy = yaml.safe_load((REPO_ROOT / "examples/compose/docker-compose.caddy.yml").read_text())
    mounts = caddy["services"]["caddy"]["volumes"]
    assert any(m.startswith("./Caddyfile:") for m in mounts)
    assert (REPO_ROOT / "examples/compose/Caddyfile").is_file()
