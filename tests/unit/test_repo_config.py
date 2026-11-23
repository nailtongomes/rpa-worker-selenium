"""Validação de YAML de workflows e exemplos de docker compose."""

import shutil
import subprocess

import pytest
import yaml

from conftest import REPO_ROOT

WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
COMPOSE_FILES = sorted((REPO_ROOT / "examples").glob("**/docker-compose*.yml"))
SHELL_SCRIPTS = sorted(
    [*(REPO_ROOT / "scripts").glob("*.sh"), *(REPO_ROOT / "examples").glob("**/*.sh"), *(REPO_ROOT / "image").glob("**/*.sh")]
)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid_yaml(path):
    data = yaml.safe_load(path.read_text())
    assert "jobs" in data and data["jobs"], f"{path.name} sem jobs"


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_compose_is_valid_yaml(path):
    data = yaml.safe_load(path.read_text())
    assert data.get("services"), f"{path.name} sem services"
    assert "version" not in data, "o campo 'version' é obsoleto no Compose Spec"


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_compose_uses_published_image(path):
    data = yaml.safe_load(path.read_text())
    for name, svc in data["services"].items():
        if "rpa" in name:
            image = svc.get("image", "")
            assert "ghcr.io/nailtongomes/rpa-worker-selenium" in image, name


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _docker_compose_available(), reason="docker compose indisponível")
@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
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


@pytest.mark.parametrize("path", SHELL_SCRIPTS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_shell_scripts_syntax_and_mode(path):
    import os

    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert os.access(path, os.X_OK), f"{path.name} precisa ser executável"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck não instalado")
@pytest.mark.parametrize("path", SHELL_SCRIPTS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_shell_scripts_shellcheck_errors(path):
    result = subprocess.run(["shellcheck", "--severity=error", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_multi_worker_compose_has_unique_workers():
    """Cada worker precisa de nome, WORKER_ID e pasta de dados exclusivos."""
    data = yaml.safe_load((REPO_ROOT / "examples/server/docker-compose.yml").read_text())
    services = data["services"]
    assert len(services) >= 4
    ids = [svc["environment"]["WORKER_ID"] for svc in services.values()]
    names = [svc["container_name"] for svc in services.values()]
    volumes = [v.split(":")[0] for svc in services.values() for v in svc["volumes"]]
    assert ids == names == list(services), "WORKER_ID/container_name devem ser iguais ao nome do serviço"
    assert len(set(volumes)) == len(volumes), "workers não podem compartilhar pastas de dados"
    for name, svc in services.items():
        assert svc["restart"] == "always"
        assert all(v.startswith(f"./data/{name}/") for v in svc["volumes"]), name
