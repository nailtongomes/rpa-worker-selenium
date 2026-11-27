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


def test_seleniumbase_is_pinned(dockerfile_text):
    """Versão fixa (resolvida junto com o requirements.txt, num pip só); "latest" é o comportamento
    antigo, usado pelo canário do nightly para validar versões novas antes de mudar o pin."""
    assert "ARG SELENIUMBASE_REFRESH" in dockerfile_text
    assert re.search(r"^ARG SELENIUMBASE_VERSION=\d+\.\d+\.\d+$", dockerfile_text, re.MULTILINE)
    assert 'pip install -r requirements.txt "seleniumbase==${SELENIUMBASE_VERSION}"' in dockerfile_text
    assert 'if [ "$SELENIUMBASE_VERSION" = "latest" ]' in dockerfile_text
    requirement = next(l for l in (REPO_ROOT / "requirements.txt").read_text().splitlines()
                       if l.split("#")[0].strip().startswith("seleniumbase"))
    assert requirement.split("#")[0].strip() == "seleniumbase", "versão do SeleniumBase só no Dockerfile"


def test_chrome_allows_popups(dockerfile_text):
    """Regressão do SeleniumBase 4.58 no modo UC (docs/CHROMEDRIVER_STABILITY.md)."""
    assert '{"DefaultPopupsSetting": 1}' in dockerfile_text
    assert "/etc/opt/chrome/policies/managed /etc/opt/chrome_for_testing/policies/managed" in dockerfile_text


def test_seleniumbase_drivers_are_the_image_chromedriver(dockerfile_text):
    """Driver()/uc/cft prontos com o ChromeDriver e o Chrome da imagem, sem download em runtime."""
    warm = dockerfile_text[dockerfile_text.index('RUN D="$(python -c'):]
    warm = warm[:warm.index("\n\n")]
    assert 'install -m 0755 /usr/local/bin/chromedriver "$D/chromedriver"' in warm
    assert 'ln -s /opt/chrome "$D/cft_drivers/chrome-linux64"' in warm
    for kw in ("dict(uc=True, incognito=True)", "dict(uc=True, cft=True)", "dict()", "dict(cft=True)"):
        assert kw in warm
    assert "cmp /usr/local/bin/chromedriver" in warm and "ln -f" in warm


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


def test_image_info_is_written_in_the_last_layer(dockerfile_text):
    """A revisão muda a cada commit: o passo que a grava fica depois do código do /app, no fim,
    para não invalidar o cache das camadas pesadas."""
    copy_app = dockerfile_text.index("COPY image/app/ /app/")
    arg = dockerfile_text.index("ARG IMAGE_REVISION=dev")
    write = dockerfile_text.index("python /app/image_info.py write")
    assert copy_app < arg < write
    assert '--revision "${IMAGE_REVISION}" --created "${IMAGE_CREATED}"' in dockerfile_text
    assert "RUN " not in dockerfile_text[write:].split("\n", 1)[1]


# --- Tamanho da imagem --------------------------------------------------------
# Num Dockerfile, mexer (chown/chmod/patch) numa camada posterior grava uma segunda cópia
# de cada arquivo tocado. Foi assim que a venv passou a ocupar o dobro (~670 MB a mais).

def _run_blocks(dockerfile_text):
    """Cada instrução RUN completa (com as continuações de linha)."""
    return re.findall(r"^RUN .*?(?<!\\)$", dockerfile_text, re.MULTILINE | re.DOTALL)


def test_venv_owner_is_set_in_the_install_layer(dockerfile_text):
    blocks = _run_blocks(dockerfile_text)
    pip_layer = next(b for b in blocks if "pip install -r requirements.txt" in b)
    assert "chown -R rpauser:rpauser /opt/venv" in pip_layer
    assert "pip install websockify" in pip_layer, "websockify fora da camada do pip duplica o que ele atualiza"
    others = [b for b in blocks if b != pip_layer]
    assert not [b for b in others if "/opt/venv" in b and ("chown" in b or "pip install" in b)]


def test_chromedriver_is_copied_and_patched_in_one_layer(dockerfile_text):
    assert "COPY --from=builder /downloads/chromedriver-dist" not in dockerfile_text
    assert "COPY image/patch_chromedriver.py" not in dockerfile_text
    patch = next(b for b in _run_blocks(dockerfile_text) if "patch_chromedriver.py" in b)
    assert "--mount=type=bind,from=builder,source=/downloads/chromedriver-dist/chromedriver" in patch
    assert "install -m 0755" in patch and "python3 /tmp/patch_chromedriver.py" in patch


def test_slim_dpkg_config_comes_before_any_package(dockerfile_text):
    runtime = dockerfile_text[dockerfile_text.index("FROM debian:trixie\n"):]
    assert runtime.index("path-exclude=/usr/share/doc/*") < runtime.index("RUN apt-get")
    for kept in ("/usr/share/doc/*/copyright", "/usr/share/locale/pt_BR/*", "/usr/share/locale/locale.alias"):
        assert f"path-include={kept}" in runtime


def test_unused_heavy_packages_stay_out(dockerfile_text):
    """Java 21 (o PJeOffice traz o Java 8 dele), pcsc-tools (Perl, diagnóstico de token A3)."""
    assert "openjdk" not in dockerfile_text
    assert not re.search(r"^\s+pcsc-tools", dockerfile_text, re.MULTILINE)
    assert "ln -s /opt/pjeoffice/jre/bin/java /usr/local/bin/java" in dockerfile_text
    assert "ln -s /opt/pjeoffice/jre/bin/keytool /usr/local/bin/keytool" in dockerfile_text
    assert "! -name 'pt-BR.*' ! -name 'en-US.*' -delete" in dockerfile_text


def test_legacy_dockerfile_is_kept():
    """A versão anterior (3,8 GB) fica como referência/rollback; o release só usa o Dockerfile.trixie."""
    legacy = (REPO_ROOT / "legacy" / "Dockerfile.trixie").read_text()
    assert "openjdk-21-jre-headless" in legacy and "RUN chown -R rpauser:rpauser /opt/venv" in legacy
