"""As receitas (recipes/) precisam funcionar como estão: copiar e rodar.

Valida as receitas contra o que o shutup-and-run aceita (campos, nomes, limites padrão de
um PC compartilhado, caminhos do repasse de certificado), contra o que a imagem lê
(variáveis) e contra vazamento de segredos. A execução de verdade da receita de teste do
A1 é um cenário do portão (scripts/test-image.sh)."""

import importlib.util
import json
import re

import pytest
import yaml

from conftest import REPO_ROOT

RECIPES = REPO_ROOT / "recipes"
IMAGE = "ghcr.io/nailtongomes/rpa-worker-selenium"

_spec = importlib.util.spec_from_file_location("run_recipe", REPO_ROOT / "scripts" / "run-recipe.py")
run_recipe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_recipe)

# shutup-and-run, src/certificate.rs (repasse de certificado): caminhos fixos no container
SAR_CERT = "/run/shutup-and-run/certificate/client.pfx"
SAR_PASSWORD = "/run/shutup-and-run/secrets/certificate-password"
# perfil shared-pc (padrão no Windows): por tarefa, 1 CPU e 2 GiB; pedir mais é recusado
SHARED_PC_CPU = 1
SHARED_PC_MEMORY = 2 * 1024**3

JSON_RECIPES = sorted(RECIPES.rglob("*.json"))
SAR_RECIPES = sorted((RECIPES / "shutup-and-run").glob("*.json"))
COMPOSE_RECIPES = sorted(RECIPES.rglob("compose.yml"))
MARKDOWN = sorted(RECIPES.rglob("*.md"))

# Variáveis lidas pela imagem: prefixos do contrato. As demais (API_TOKEN, RESULT_URL, SITE_URL)
# são do script da tarefa.
IMAGE_PREFIXES = ("USE_", "WORKER_", "A1_", "EGRESS_", "SCRIPT_", "HELPER_", "SCREEN_", "PJEOFFICE_",
                  "TASK_", "CHROME_", "VNC_", "NOVNC_")
# quem lê: a imagem (/app) ou os scripts das próprias receitas (ex.: WORKER_ID no modelo_tarefa.py)
APP_SOURCES = "\n".join(p.read_text(encoding="utf-8")
                        for p in [*(REPO_ROOT / "image" / "app").glob("*"), *RECIPES.rglob("*.py")]
                        if p.is_file() and p.suffix in (".py", ".sh"))


def _size(text: str) -> int:
    units = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    m = re.fullmatch(r"(\d+)([kmg]?)", str(text).lower())
    assert m, text
    return int(m.group(1)) * units[m.group(2)]


def _body(path):
    return run_recipe.load_recipe(path)[1]


def _all_env(body: dict) -> dict:
    return {**(body.get("env") or {}), **(body.get("secret_env") or {})}


def test_there_are_recipes():
    assert (RECIPES / "README.md").is_file()
    assert {p.name for p in SAR_RECIPES} >= {"teste-a1.json", "rotina.json", "tarefa-poll.json"}


@pytest.mark.parametrize("path", JSON_RECIPES, ids=lambda p: str(p.relative_to(RECIPES)))
def test_recipe_is_accepted(path):
    kind, body = run_recipe.load_recipe(path)
    assert body["image"].split("@")[0].rsplit(":", 1)[0] == IMAGE
    assert kind in ("managed", "task")


@pytest.mark.parametrize("path", SAR_RECIPES, ids=lambda p: p.name)
def test_shutup_and_run_recipe_fits_a_shared_pc(path):
    body = _body(path)
    assert body.get("cpu", 0) <= SHARED_PC_CPU
    assert _size(body["memory"]) <= SHARED_PC_MEMORY
    assert _size(body["memory"]) >= 2 * 1024**3, "pico medido com PJeOffice ~1,1 GB: 2g de memória"
    assert body.get("shm"), "Chrome precisa de /dev/shm"
    assert body.get("timeout_secs"), "toda receita tem prazo"


@pytest.mark.parametrize("path", SAR_RECIPES, ids=lambda p: p.name)
def test_shutup_and_run_recipe_uses_certificate_passthrough(path):
    env = _body(path)["env"]
    assert env["A1_PFX_PATH"] == SAR_CERT
    assert env["A1_PFX_PASSWORD_FILE"] == SAR_PASSWORD
    assert env["USE_XVFB"] == "1", "browser em janela no Xvfb (furtividade)"
    assert run_recipe.CONTAINER_CERT == SAR_CERT and run_recipe.CONTAINER_PASSWORD == SAR_PASSWORD


@pytest.mark.parametrize("path", JSON_RECIPES, ids=lambda p: str(p.relative_to(RECIPES)))
def test_recipe_variables_exist_in_the_image(path):
    for key in _all_env(_body(path)):
        if key.startswith(IMAGE_PREFIXES):
            assert re.search(rf"\b{key}\b", APP_SOURCES), f"{key} não é lida pela imagem nem pelos scripts das receitas"


@pytest.mark.parametrize("path", JSON_RECIPES, ids=lambda p: str(p.relative_to(RECIPES)))
def test_recipe_has_no_secrets(path):
    body = _body(path)
    env = body.get("env") or {}
    assert not any("PASSWORD" in k and not k.endswith("_FILE") for k in env), "senha só por arquivo"
    assert all(v is None for v in (body.get("secret_env") or {}).values()), "segredo sem valor no arquivo"
    for key, value in env.items():
        if value.startswith("http"):
            host = re.match(r"https?://([^/:?]+)", value).group(1)
            assert host.endswith("example.com"), f"{key}: use example.com nos exemplos"


@pytest.mark.parametrize("path", COMPOSE_RECIPES, ids=lambda p: str(p.relative_to(RECIPES)))
def test_compose_recipes(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "version" not in data
    worker = data["services"]["worker"]
    assert worker["image"].startswith(IMAGE)
    assert _size(worker["mem_limit"]) >= 2 * 1024**3
    env = worker["environment"]
    assert not any("PASSWORD" in k and not k.endswith("_FILE") for k in env)
    assert "EGRESS_PROXY_URL" not in env, "a URL do relay tem senha: EGRESS_PROXY_URL_FILE"
    for port in worker.get("ports", []):
        assert str(port).startswith("127.0.0.1:"), "noVNC/VNC sem senha: só em 127.0.0.1"
    for key in env:
        if key.startswith(IMAGE_PREFIXES):
            assert re.search(rf"\b{key}\b", APP_SOURCES), f"{key} não é lida pela imagem nem pelos scripts das receitas"


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: str(p.relative_to(RECIPES)))
def test_markdown_links_resolve(path):
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        file_part = target.split("#", 1)[0]
        assert (path.parent / file_part).exists(), f"{path.name}: link quebrado {target}"


def test_readme_anchors_used_by_the_index_exist():
    index = (RECIPES / "README.md").read_text(encoding="utf-8")
    guide = (RECIPES / "shutup-and-run" / "README.md").read_text(encoding="utf-8")
    slugs = {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
             for h in re.findall(r"^#+ (.+)$", guide, re.M)}
    for anchor in re.findall(r"shutup-and-run/README\.md#([\w-]+)", index):
        assert anchor in slugs, f"âncora inexistente: #{anchor}"


def test_gitignore_keeps_certificates_out():
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.pfx", "*.p12", "recipes/**/segredos/", ".env"):
        assert pattern in ignored


# --- scripts/run-recipe.py -----------------------------------------------------------------

def _recipe(tmp_path, **fields):
    base = {"name": "teste", "image": IMAGE, "policy": "once", "memory": "2g", "shm": "1g", "cpu": 1,
            "env": {"USE_XVFB": "1"}}
    base.update(fields)
    path = tmp_path / "r.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def test_command_mirrors_shutup_and_run(tmp_path):
    pfx, pw = tmp_path / "a1.pfx", tmp_path / "senha"
    pfx.write_bytes(b"pfx")
    pw.write_text("S3nha-NAO-PODE-VAZAR")
    body = _body(_recipe(tmp_path, env={"USE_XVFB": "1", "SCRIPT_URL": "https://x.example.com/?token=TOKEN-1"},
                         secret_env={"API_TOKEN": None}, command=["python", "/app/preflight.py"]))
    argv, env = run_recipe.build_command(body, pfx=pfx, password_file=pw, name="r1",
                                         environ={"API_TOKEN": "TOKEN-2", "PATH": "/bin"})
    joined = " ".join(argv)
    for flag in ("--init", "--pids-limit 4096", "--cpus 1", "--memory 2g", "--memory-swap 2g", "--shm-size 1g"):
        assert flag in joined
    assert f"{pfx.resolve()}:{SAR_CERT}:ro" in argv and f"{pw.resolve()}:{SAR_PASSWORD}:ro" in argv
    assert argv[-3:] == [IMAGE, "python", "/app/preflight.py"]
    # valores nunca no argv (ps): vão pelo ambiente do processo
    assert "TOKEN-1" not in joined and "TOKEN-2" not in joined and "S3nha" not in joined
    assert env["API_TOKEN"] == "TOKEN-2" and env["SCRIPT_URL"].endswith("TOKEN-1")
    assert env["SHUTUP_AND_RUN_CERT_PATH"] == SAR_CERT
    assert not any(a.startswith(("-p", "--publish", "--privileged", "--network")) for a in argv)


def test_missing_secret_does_not_run(tmp_path):
    body = _body(_recipe(tmp_path, secret_env={"SCRIPT_URL": None}))
    with pytest.raises(run_recipe.RecipeError, match="SCRIPT_URL"):
        run_recipe.build_command(body, environ={})


def test_task_cannot_override_certificate_paths(tmp_path):
    body = _body(_recipe(tmp_path, env={"SHUTUP_AND_RUN_CERT_PATH": "/mine"}))
    argv, env = run_recipe.build_command(body, environ={})
    assert "SHUTUP_AND_RUN_CERT_PATH" not in argv


@pytest.mark.parametrize("fields, error", [
    ({"ports": ["8080:8080"]}, "recusa"),
    ({"name": "Com Espaco"}, "name"),
    ({"policy": "interval"}, "interval_secs"),
    ({"policy": "once", "interval_secs": 300}, "interval_secs"),
    ({"memory": "dois giga"}, "memory"),
    ({"env": {"1INVALIDA": "x"}}, "variável"),
    ({"env": {"A": "1"}, "secret_env": {"A": None}}, "env e secret_env"),
])
def test_invalid_recipes_are_refused(tmp_path, fields, error):
    with pytest.raises(run_recipe.RecipeError, match=error):
        run_recipe.load_recipe(_recipe(tmp_path, **fields))


def test_poll_answer_only_has_task(tmp_path):
    path = tmp_path / "poll.json"
    path.write_text(json.dumps({"task": {"image": IMAGE}, "extra": 1}))
    with pytest.raises(run_recipe.RecipeError, match="task"):
        run_recipe.load_recipe(path)


def test_dry_run_cli(capsys):
    rc = run_recipe.main([str(RECIPES / "shutup-and-run" / "teste-a1.json"), "--dry-run"])
    assert rc == 0
    assert "--memory-swap 2g" in capsys.readouterr().out
