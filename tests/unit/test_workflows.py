"""
Regras dos workflows do GitHub Actions (Fase 2).

Protegem as garantias do release: nada é publicado sem passar pelo portão
scripts/test-image.sh, o CI testa a mesma configuração do release e nenhuma
falha de teste é mascarada.
"""

import os
import re

import pytest
import yaml

from conftest import REPO_ROOT

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RELEASE = WORKFLOWS_DIR / "build-push-ghcr.yml"
CI = WORKFLOWS_DIR / "ci.yml"
NIGHTLY = WORKFLOWS_DIR / "nightly.yml"
GATE = "scripts/test-image.sh"


def _load(path):
    data = yaml.safe_load(path.read_text())
    # PyYAML lê a chave `on` como True
    data["on"] = data.pop(True, data.get("on"))
    return data


def _steps(workflow, job):
    return workflow["jobs"][job]["steps"]


def _index(steps, predicate, what):
    for i, step in enumerate(steps):
        if predicate(step):
            return i
    pytest.fail(f"passo não encontrado: {what}")


def _build_args(step):
    return {line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
            for line in step["with"]["build-args"].splitlines() if "=" in line}


def _build_step(workflow, job):
    steps = _steps(workflow, job)
    return steps[_index(steps, lambda s: "docker/build-push-action" in s.get("uses", ""), "build")]


def test_gate_script_is_executable():
    gate = REPO_ROOT / GATE
    assert gate.is_file() and os.access(gate, os.X_OK)


def test_release_pushes_only_after_quality_gate():
    release = _load(RELEASE)
    steps = _steps(release, "build-and-push")
    build = _index(steps, lambda s: "docker/build-push-action" in s.get("uses", ""), "build")
    gate = _index(steps, lambda s: GATE in s.get("run", ""), "quality gate")
    push = _index(steps, lambda s: "docker push" in s.get("run", ""), "docker push")

    assert build < gate < push, "ordem esperada: build -> test-image.sh -> push"
    build_with = steps[build]["with"]
    assert build_with.get("push") is False, "o build não pode publicar antes dos testes"
    assert build_with.get("load") is True, "a imagem testada precisa ser a imagem publicada"
    meta = steps[_index(steps, lambda s: s.get("id") == "meta", "meta")]["run"]
    assert "rpa-worker:candidate" in meta, "a imagem candidata precisa de uma tag local"
    assert "rpa-worker:candidate" in steps[gate]["run"]
    for step in steps[gate:push + 1]:
        assert not step.get("continue-on-error") or "docker push" not in step.get("run", ""), \
            "o push não pode ignorar falhas"
    assert not steps[gate].get("continue-on-error"), "o portão não pode ser ignorado"


def test_release_triggers_on_everything_that_changes_the_image():
    paths = _load(RELEASE)["on"]["push"]["paths"]
    for required in ["Dockerfile.trixie", "requirements.txt", "image/**"]:
        assert required in paths, f"release não dispara quando {required} muda"


def test_release_never_runs_concurrently():
    release = _load(RELEASE)
    assert release["concurrency"]["cancel-in-progress"] is False


def test_ci_builds_exactly_like_the_release():
    release_args = _build_args(_build_step(_load(RELEASE), "build-and-push"))
    ci_args = _build_args(_build_step(_load(CI), "image"))
    nightly_args = _build_args(_build_step(_load(NIGHTLY), "production-image"))
    feature_args = {k: v for k, v in release_args.items() if k.startswith(("BUILD_", "ENABLE_"))}
    assert feature_args, "release sem build-args de recursos"
    for name, args in [("ci.yml", ci_args), ("nightly.yml", nightly_args)]:
        got = {k: v for k, v in args.items() if k.startswith(("BUILD_", "ENABLE_"))}
        assert got == feature_args, f"{name} constrói com flags diferentes do release: {got} != {feature_args}"


@pytest.mark.parametrize("path", [CI, RELEASE, NIGHTLY], ids=lambda p: p.name)
def test_quality_gate_is_used(path):
    assert GATE in path.read_text()


@pytest.mark.parametrize("path", sorted(WORKFLOWS_DIR.glob("*.yml")), ids=lambda p: p.name)
def test_no_masked_failures(path):
    """Nenhum teste pode ter a falha engolida por '|| exit 0' / '|| true'."""
    for n, line in enumerate(path.read_text().splitlines(), 1):
        assert "|| exit 0" not in line, f"{path.name}:{n}: '|| exit 0' mascara falhas"
        if re.search(r"pytest|test-image|smoke_test|test_browser", line):
            assert not re.search(r"\|\|\s*true\b", line), f"{path.name}:{n}: '|| true' mascara falha de teste"


def test_nightly_builds_without_cache():
    build = _build_step(_load(NIGHTLY), "production-image")
    assert build["with"].get("no-cache") is True
    assert "schedule" in _load(NIGHTLY)["on"]
