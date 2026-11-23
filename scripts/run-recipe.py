#!/usr/bin/env python3
"""
Roda uma receita do shutup-and-run (definição de container gerenciado ou tarefa de
poll) com o Docker deste computador, do mesmo jeito que o shutup-and-run rodaria.

Serve para testar uma receita antes de instalá-la no PC do cliente, e é o que o
portão de qualidade (scripts/test-image.sh) usa para provar que as receitas funcionam.

    scripts/run-recipe.py recipes/shutup-and-run/teste-a1.json \\
        --pfx ~/certificados/meu-a1.pfx --password-file ~/certificados/senha.txt

    scripts/run-recipe.py recipes/shutup-and-run/teste-a1.json --dry-run   # só mostra o comando

O que imita do shutup-and-run (perfil shared-pc):
  - limites da receita: --cpus, --memory e --memory-swap iguais (sem swap extra), --shm-size;
  - --init e --pids-limit 4096, como todo job do shutup-and-run;
  - sem portas, sem volumes, sem privilégios: só o que um pedido pode ter;
  - repasse do certificado (com --pfx/--password-file): os dois arquivos somente leitura nos
    caminhos fixos /run/shutup-and-run/... e as variáveis SHUTUP_AND_RUN_CERT_PATH e
    SHUTUP_AND_RUN_CERT_PASSWORD_FILE;
  - secret_env com valor null: o valor vem da variável de ambiente de mesmo nome deste
    computador (sem ela, não roda, como no shutup-and-run);
  - timeout_secs: o container é parado ao fim do prazo (exit 124).

Valores de env nunca vão para a linha de comando do docker (ps): são passados pelo
ambiente do processo (`docker run -e NOME`). A senha do certificado só existe no arquivo.

Exit: o exit code do container (124 = timeout), 2 = receita ou argumentos inválidos.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

# Constantes do shutup-and-run (src/certificate.rs e src/launcher.rs)
CONTAINER_CERT = "/run/shutup-and-run/certificate/client.pfx"
CONTAINER_PASSWORD = "/run/shutup-and-run/secrets/certificate-password"
ENV_CERT = "SHUTUP_AND_RUN_CERT_PATH"
ENV_PASSWORD_FILE = "SHUTUP_AND_RUN_CERT_PASSWORD_FILE"
PIDS_LIMIT = 4096

# Campos aceitos (o shutup-and-run recusa campos desconhecidos)
MANAGED_FIELDS = {"name", "image", "command", "env", "secret_env", "cpu", "memory", "shm",
                  "timeout_secs", "policy", "interval_secs", "enabled"}
TASK_FIELDS = {"image", "job_key", "env", "command", "timeout_secs", "cpu", "memory", "shm", "callback_url"}
POLICIES = {"once", "interval", "always"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")
SIZE_RE = re.compile(r"^[0-9]+[kmgKMG]?$")


class RecipeError(ValueError):
    pass


def load_recipe(path: Path) -> tuple[str, dict]:
    """Devolve ("managed"|"task", campos), validando como o shutup-and-run valida."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecipeError(f"{path}: não é um JSON legível ({exc})") from None
    if not isinstance(data, dict):
        raise RecipeError(f"{path}: esperado um objeto JSON")

    if "task" in data:  # resposta de poll: {"task": {...}}
        kind, body, allowed = "task", data["task"], TASK_FIELDS
        if set(data) != {"task"}:
            raise RecipeError(f"{path}: a resposta de poll só tem o campo task")
    elif "policy" in data:
        kind, body, allowed = "managed", data, MANAGED_FIELDS
    else:
        kind, body, allowed = "task", data, TASK_FIELDS  # pedido de job (push) ou manifesto

    unknown = set(body) - allowed
    if unknown:
        raise RecipeError(f"{path}: campos que o shutup-and-run recusa: {', '.join(sorted(unknown))}")
    if not isinstance(body.get("image"), str) or not body["image"]:
        raise RecipeError(f"{path}: falta image")

    env = body.get("env", {}) or {}
    secret_env = body.get("secret_env", {}) or {}
    if len(env) + len(secret_env) > 128:
        raise RecipeError(f"{path}: env aceita no máximo 128 variáveis")
    for key, value in [*env.items(), *secret_env.items()]:
        if not ENV_KEY_RE.match(key):
            raise RecipeError(f"{path}: nome de variável inválido: {key}")
        if value is not None and (not isinstance(value, str) or len(value) > 16 * 1024 or "\0" in value):
            raise RecipeError(f"{path}: valor inválido para {key}")
    both = set(env) & set(secret_env)
    if both:
        raise RecipeError(f"{path}: variável em env e secret_env ao mesmo tempo: {', '.join(sorted(both))}")

    command = body.get("command")
    if command is not None and (not isinstance(command, list) or len(command) > 32
                                or not all(isinstance(a, str) and a for a in command)):
        raise RecipeError(f"{path}: command precisa ser uma lista de até 32 textos não vazios")
    for field in ("memory", "shm"):
        if field in body and not SIZE_RE.match(str(body[field])):
            raise RecipeError(f"{path}: {field} inválido: {body[field]!r} (ex.: \"2g\", \"512m\")")

    if kind == "managed":
        if not NAME_RE.match(str(body.get("name", ""))):
            raise RecipeError(f"{path}: name precisa ter 1-40 letras minúsculas, dígitos, '-' ou '_'")
        policy = body.get("policy")
        if policy not in POLICIES:
            raise RecipeError(f"{path}: policy precisa ser once, interval ou always")
        if policy == "interval" and not (60 <= int(body.get("interval_secs") or 0)):
            raise RecipeError(f"{path}: policy interval precisa de interval_secs >= 60")
        if policy != "interval" and "interval_secs" in body:
            raise RecipeError(f"{path}: interval_secs é só para policy interval")
    return kind, body


def build_command(body: dict, *, image: str | None = None, pfx: Path | None = None,
                  password_file: Path | None = None, name: str | None = None,
                  extra_args: list | None = None, environ: dict | None = None) -> tuple[list, dict]:
    """Monta (argv do docker, ambiente do processo). Nenhum valor de env entra no argv."""
    environ = dict(os.environ if environ is None else environ)
    child_env = dict(environ)
    argv = ["docker", "run", "--rm", "--init", "--pids-limit", str(PIDS_LIMIT)]
    if name:
        argv += ["--name", name]
    if body.get("cpu"):
        argv += ["--cpus", str(body["cpu"])]
    if body.get("memory"):
        argv += ["--memory", str(body["memory"]), "--memory-swap", str(body["memory"])]
    if body.get("shm"):
        argv += ["--shm-size", str(body["shm"])]

    def pass_env(key: str, value: str) -> None:
        child_env[key] = value
        argv.extend(["-e", key])

    for key, value in (body.get("env") or {}).items():
        if key in (ENV_CERT, ENV_PASSWORD_FILE):
            continue  # o shutup-and-run descarta o que a tarefa der a essas duas
        pass_env(key, value)

    missing = []
    for key, value in (body.get("secret_env") or {}).items():
        value = value if value is not None else environ.get(key)
        if value is None:
            missing.append(key)
        else:
            pass_env(key, value)
    if missing:
        raise RecipeError("segredo sem valor (defina no ambiente deste computador): " + ", ".join(missing))

    if (pfx is None) != (password_file is None):
        raise RecipeError("--pfx e --password-file andam juntos")
    if pfx is not None:
        for f in (pfx, password_file):
            if not Path(f).is_file():
                raise RecipeError(f"arquivo não encontrado: {f}")
        argv += ["-v", f"{Path(pfx).resolve()}:{CONTAINER_CERT}:ro",
                 "-v", f"{Path(password_file).resolve()}:{CONTAINER_PASSWORD}:ro"]
        pass_env(ENV_CERT, CONTAINER_CERT)
        pass_env(ENV_PASSWORD_FILE, CONTAINER_PASSWORD)

    argv += list(extra_args or [])
    argv.append(image or body["image"])
    argv += list(body.get("command") or [])
    return argv, child_env


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recipe", type=Path, help="JSON da receita (gerenciado, tarefa de poll ou pedido de job)")
    parser.add_argument("--pfx", type=Path, help="certificado A1 (.pfx/.p12) a repassar")
    parser.add_argument("--password-file", type=Path, help="arquivo com a senha do certificado (uma linha)")
    parser.add_argument("--image", help="outra imagem no lugar da receita (ex.: rpa-worker:local)")
    parser.add_argument("--docker-arg", action="append", default=[],
                        help="argumento extra para o docker run (repetível)")
    parser.add_argument("--dry-run", action="store_true", help="só mostra o comando")
    args = parser.parse_args(argv)

    try:
        kind, body = load_recipe(args.recipe)
        cmd, env = build_command(body, image=args.image, pfx=args.pfx, password_file=args.password_file,
                                 name=f"recipe-{uuid.uuid4().hex[:8]}", extra_args=args.docker_arg)
    except RecipeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    timeout = body.get("timeout_secs")
    label = body.get("name") or body.get("job_key") or args.recipe.name
    print(f"🍳 receita {label} ({kind}): {shlex.join(cmd)}", flush=True)
    if args.dry_run:
        return 0
    container = cmd[cmd.index("--name") + 1]
    try:
        return subprocess.run(cmd, env=env, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f"⏱️  timeout_secs={timeout} esgotado: parando {container}", file=sys.stderr, flush=True)
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        return 124


if __name__ == "__main__":
    sys.exit(main())
