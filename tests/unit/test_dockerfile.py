"""
Testes estáticos do Dockerfile.trixie e do contexto de build.

Pegam, em segundos e sem Docker, os erros que hoje só apareceriam no meio de
um build de ~20 minutos: COPY de arquivo inexistente, arquivo fora do
.dockerignore, build-arg do release que o Dockerfile não declara etc.
"""

import fnmatch
import os
import re

import pytest
import yaml

from conftest import APP_DIR, REPO_ROOT

RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-push-ghcr.yml"


def _local_copy_sources(dockerfile_text):
    """Fontes de COPY que vêm do contexto (ignora COPY --from=...)."""
    sources = []
    for line in dockerfile_text.splitlines():
        line = line.strip()
        if not line.startswith("COPY ") or "--from=" in line:
            continue
        parts = [p for p in line.split()[1:] if not p.startswith("--")]
        sources.extend(parts[:-1])
    return sources


def _dockerignore_allows(path: str) -> bool:
    """Avalia o .dockerignore (allowlist) para um path relativo ao repo."""
    allowed = True
    for raw in (REPO_ROOT / ".dockerignore").read_text().splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        negate = rule.startswith("!")
        pattern = rule[1:] if negate else rule
        pattern = pattern.rstrip("/")
        candidates = [path] + [path[: i] for i in range(len(path)) if path[i] == "/"]
        if any(fnmatch.fnmatch(c, pattern) or fnmatch.fnmatch(c, pattern.replace("**/", "")) for c in candidates):
            allowed = negate
    return allowed


def test_copy_sources_exist(dockerfile_text):
    sources = _local_copy_sources(dockerfile_text)
    assert sources, "nenhum COPY local encontrado"
    missing = [s for s in sources if not (REPO_ROOT / s).exists()]
    assert not missing, f"COPY aponta para arquivos inexistentes: {missing}"


def test_copy_sources_are_in_build_context(dockerfile_text):
    blocked = [s for s in _local_copy_sources(dockerfile_text) if not _dockerignore_allows(s.rstrip("/"))]
    assert not blocked, f"arquivos copiados mas excluídos pelo .dockerignore: {blocked}"


@pytest.mark.parametrize("path", ["README.md", "docs/WORKER.md", "tests/unit/test_dockerfile.py", "examples/compose/docker-compose.yml", ".env", ".git"])
def test_non_image_files_stay_out_of_build_context(path):
    assert not _dockerignore_allows(path), f"{path} não deveria ir para o contexto de build"


def test_production_image_only_ships_image_app(dockerfile_text):
    assert "COPY . ." not in dockerfile_text, "use COPY explícito (image/app/ -> /app/)"
    assert "COPY image/app/ /app/" in dockerfile_text


def test_entrypoint_contract(dockerfile_text):
    assert 'ENTRYPOINT ["/app/entrypoint.sh"]' in dockerfile_text
    for name in ["entrypoint.sh", "script_downloader.py", "smoke_test.py", "task_server.py"]:
        f = APP_DIR / name
        assert f.is_file(), f"image/app/{name} ausente"
        assert os.access(f, os.X_OK), f"image/app/{name} precisa ser executável"


def test_release_build_args_are_declared(dockerfile_text):
    """Todo build-arg passado pelo release precisa de um ARG no Dockerfile."""
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    steps = workflow["jobs"]["build-and-push"]["steps"]
    build = next(s for s in steps if "docker/build-push-action" in s.get("uses", ""))
    assert build["with"]["file"].lstrip("./") == "Dockerfile.trixie"
    args = [l.split("=", 1)[0].strip() for l in build["with"]["build-args"].splitlines() if "=" in l]
    declared = set(re.findall(r"^ARG\s+([A-Z0-9_]+)", dockerfile_text, re.MULTILINE))
    missing = sorted(set(args) - declared)
    assert not missing, f"build-args do release sem ARG no Dockerfile: {missing}"


def test_seleniumbase_tracks_latest(dockerfile_text):
    assert "ARG SELENIUMBASE_REFRESH" in dockerfile_text
    assert "pip install --upgrade seleniumbase" in dockerfile_text


def test_chrome_and_chromedriver_share_version(dockerfile_text):
    """Chrome e ChromeDriver vêm do mesmo CHROME_VERSION (Chrome for Testing)."""
    assert re.search(r"^ARG CHROME_VERSION=\d+\.\d+\.\d+\.\d+$", dockerfile_text, re.MULTILINE)
    assert "${CHROME_VERSION}/${cft}/chromedriver-${cft}.zip" in dockerfile_text
    assert "${CHROME_VERSION}/${cft}/chrome-${cft}.zip" in dockerfile_text


def test_downloads_cover_amd64_and_arm64(dockerfile_text):
    """amd64 (:latest) e arm64 (:latest-arm64) baixam o binário certo; outra arquitetura falha no build."""
    assert "ARG TARGETARCH" in dockerfile_text
    for expected in ("amd64) cft=linux64", "arm64) cft=linux-arm64",
                     "amd64) ff=linux-x86_64; gd=linux64", "arm64) ff=linux-aarch64; gd=linux-aarch64"):
        assert expected in dockerfile_text
    assert dockerfile_text.count('unsupported TARGETARCH') == 2


def test_pjeoffice_arm64_jre_is_pinned(dockerfile_text):
    """O PJeOffice só sai para x64: no arm64 o JRE embutido é trocado pelo Zulu 8 FX aarch64, com SHA-256."""
    url = re.search(r"^ARG PJEOFFICE_JRE_ARM64_URL=(\S+)$", dockerfile_text, re.MULTILINE)
    sha = re.search(r"^ARG PJEOFFICE_JRE_ARM64_SHA256=([0-9a-f]{64})$", dockerfile_text, re.MULTILINE)
    assert url and sha
    assert url.group(1).startswith("https://cdn.azul.com/zulu/bin/zulu8.") and "-fx-jre8" in url.group(1)
    assert url.group(1).endswith("-linux_aarch64.tar.gz")
    assert 'sha256sum -c -' in dockerfile_text
