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
    assert build_with.get("tags") == "rpa-worker:candidate", \
        "o build só pode criar a tag local; as tags públicas são aplicadas no push"
    push_run = steps[push]["run"]
    assert "docker tag rpa-worker:candidate" in push_run, "as tags públicas devem vir da imagem testada"
    assert "imagetools inspect" in push_run, "o push precisa conferir o digest de cada tag no registro"
    assert "--all-tags" not in push_run
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


def test_no_step_between_gate_and_push_can_retag_latest():
    """Regressão: um `docker pull :latest` antes do push sobrescrevia a tag local
    `latest` e republicava a imagem antiga. Hoje o build não cria tags públicas."""
    steps = _steps(_load(RELEASE), "build-and-push")
    push = _index(steps, lambda s: "docker push" in s.get("run", ""), "docker push")
    for step in steps[:push]:
        assert "${IMAGE_NAME}:latest" not in str(step.get("run", "")) or "pull" in step.get("run", ""), step["name"]
    build = steps[_index(steps, lambda s: "docker/build-push-action" in s.get("uses", ""), "build")]
    assert ":latest" not in build["with"]["tags"]


# --- Actions em Node 24 + Dependabot ------------------------------------------------

# Majors mínimas que rodam em Node 24 (Node 20 foi descontinuado nos runners do GitHub)
MIN_MAJOR = {
    "actions/checkout": 6,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
    "docker/build-push-action": 7,
    "docker/setup-buildx-action": 4,
    "docker/login-action": 4,
}


def _uses():
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        for match in re.finditer(r"uses:\s*([\w.-]+/[\w.-]+)@v(\d+)", path.read_text()):
            yield path.name, match.group(1), int(match.group(2))


@pytest.mark.parametrize("workflow, action, major", list(_uses()))
def test_actions_use_node24_majors(workflow, action, major):
    if action in MIN_MAJOR:
        assert major >= MIN_MAJOR[action], f"{workflow}: {action}@v{major} < v{MIN_MAJOR[action]} (Node 24)"


def test_dependabot_updates_github_actions():
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())
    ecosystems = {u["package-ecosystem"] for u in config["updates"]}
    assert "github-actions" in ecosystems


def test_gate_scenario_titles_have_no_colon():
    """test-image.sh separa título e função por ':' — um ':' no título corta o resumo."""
    text = (REPO_ROOT / GATE).read_text()
    block = text[text.index("SCENARIOS=("):text.index(")", text.index("SCENARIOS=("))]
    for entry in re.findall(r'"([^"]+)"', block):
        assert entry.count(":") == 1, f"título com ':' em {entry!r}"


# --- GitHub Release com notas e rollback -------------------------------------------------

def test_release_publishes_notes_after_push():
    workflow = _load(RELEASE)
    job = workflow["jobs"]["build-and-push"]
    assert job["permissions"]["contents"] == "write" and job["permissions"]["packages"] == "write"
    steps = job["steps"]
    checkout = steps[_index(steps, lambda s: "actions/checkout" in s.get("uses", ""), "checkout")]
    assert checkout["with"]["fetch-depth"] == 0, "notas precisam do histórico (commits desde a versão anterior)"
    gate = _index(steps, lambda s: GATE in s.get("run", ""), "portão")
    prev = _index(steps, lambda s: s.get("id") == "prev", "versão anterior")
    push = _index(steps, lambda s: "docker push" in s.get("run", ""), "docker push")
    notes = _index(steps, lambda s: "scripts/release-notes.sh" in s.get("run", ""), "notas")
    assert gate < prev < push < notes
    # a imagem já foi publicada: falha nas notas não pode marcar o release como quebrado
    assert steps[notes].get("continue-on-error") is True and steps[prev].get("continue-on-error") is True
    assert "steps.push.outputs.digest" in steps[notes]["if"]
    assert "gh release create" in steps[notes]["run"]


def test_nightly_checks_icp_brasil_against_iti():
    job = _load(NIGHTLY)["jobs"]["icp-brasil"]
    run = " ".join(s.get("run", "") for s in job["steps"])
    assert "scripts/update-icp-brasil.py --check" in run
    assert not any(s.get("continue-on-error") for s in job["steps"]), "AC nova no ITI precisa avisar (falhar)"


def _git(repo, *args):
    import subprocess

    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_release_notes_script(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    prev = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "detalhe interno do PR")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #99 from o/feature\n\nMascarar tokens")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "commit direto na main")
    snap_old, snap_new = tmp_path / "old", tmp_path / "new"
    for snap, chrome in ((snap_old, "157"), (snap_new, "158")):
        snap.mkdir()
        (snap / "versions.txt").write_text(f"chrome {chrome}\n")
        (snap / "pip-freeze.txt").write_text("selenium==4\n")
        (snap / "dpkg.txt").write_text("libc 1\n")
    env = {**os.environ, "IMAGE_NAME": "ghcr.io/o/r", "DIGEST": "sha256:new", "SHORT_SHA": "abcdef1",
           "TIMESTAMP": "20260101-000000", "PREV_REVISION": prev, "PREV_DIGEST": "sha256:old",
           "SNAP_CURRENT": str(snap_old), "SNAP_CANDIDATE": str(snap_new), "GITHUB_REPOSITORY": "o/r"}
    out = subprocess.run([str(REPO_ROOT / "scripts" / "release-notes.sh")], cwd=repo, env=env,
                         capture_output=True, text=True, check=True).stdout
    assert "docker pull ghcr.io/o/r@sha256:new" in out
    assert f"docker pull ghcr.io/o/r:sha-{prev[:7]}" in out  # rollback
    assert f"imagetools create -t ghcr.io/o/r:latest ghcr.io/o/r:sha-{prev[:7]}" in out
    assert "- #99 Mascarar tokens" in out
    assert "commit direto na main" in out and "detalhe interno do PR" not in out
    assert "-chrome 157" in out and "+chrome 158" in out
    assert "base" not in out.split("## 📝 Mudanças")[1].split("## 🔍")[0]  # só desde a versão anterior

    # sem versão anterior conhecida: ainda gera notas, sem rollback
    env.pop("PREV_REVISION")
    out = subprocess.run([str(REPO_ROOT / "scripts" / "release-notes.sh")], cwd=repo, env=env,
                         capture_output=True, text=True, check=True).stdout
    assert "Sem informação da versão anterior" in out and "- #99 Mascarar tokens" in out


def test_gate_scenario_titles_have_no_colon():
    """test-image.sh separa título e função no primeiro ':' (um ':' no título corta o nome)."""
    text = (REPO_ROOT / "scripts" / "test-image.sh").read_text(encoding="utf-8")
    block = text[text.index("SCENARIOS=("):]
    block = block[:block.index("\n)")]
    entries = re.findall(r'^\s*"([^"]+)"', block, re.M)
    assert len(entries) >= 14
    for entry in entries:
        assert entry.count(":") == 1, entry
        assert entry.split(":")[1].startswith("scenario_"), entry
