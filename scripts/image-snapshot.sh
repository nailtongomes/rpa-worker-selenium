#!/usr/bin/env bash
# =============================================================================
# image-snapshot.sh — gera uma "foto" determinística de uma imagem Docker
#
# Usado para comparar a imagem antes/depois de uma mudança e garantir que o
# "contrato" da imagem (paths, versões, pacotes, env, entrypoint) não mudou
# sem querer.
#
# Uso:
#   scripts/image-snapshot.sh <imagem> <diretorio-saida>
#
# Exemplo:
#   scripts/image-snapshot.sh ghcr.io/nailtongomes/rpa-worker-selenium:latest snap/latest
#   scripts/image-snapshot.sh rpa-worker:local snap/local
#   diff -ru snap/latest snap/local
#
# Valores de variáveis de ambiente com cara de segredo (URL, TOKEN, SECRET,
# PASS, KEY) são mascarados para que a foto possa ser versionada no git.
# =============================================================================
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Uso: $0 <imagem> <diretorio-saida>" >&2
    exit 2
fi

IMAGE="$1"
OUT="$2"
mkdir -p "$OUT"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Imagem '$IMAGE' não encontrada localmente. Rode 'docker pull $IMAGE' ou faça o build antes." >&2
    exit 1
fi

# Executa um comando dentro da imagem sem passar pelo entrypoint (sem Xvfb,
# sem downloads, sem efeitos colaterais).
in_image() {
    docker run --rm --network none --entrypoint bash "$IMAGE" -c "$1"
}

mask_secrets='s/^([A-Za-z0-9_]*(URL|TOKEN|SECRET|PASS|PASSWORD|KEY)[A-Za-z0-9_]*)=.+$/\1=<masked>/'

echo "📸 Snapshot de $IMAGE -> $OUT"

# --- Metadados da imagem -----------------------------------------------------
{
    echo "image: $IMAGE"
    docker image inspect "$IMAGE" --format \
'repo_digests: {{json .RepoDigests}}
entrypoint: {{json .Config.Entrypoint}}
cmd: {{json .Config.Cmd}}
user: {{json .Config.User}}
workdir: {{json .Config.WorkingDir}}
exposed_ports: {{json .Config.ExposedPorts}}
healthcheck: {{json .Config.Healthcheck}}
size_bytes: {{.Size}}'
} > "$OUT/metadata.txt"

docker image inspect "$IMAGE" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | sed -E "$mask_secrets" | sed '/^$/d' | sort > "$OUT/env.txt"

docker image inspect "$IMAGE" --format '{{range $k, $v := .Config.Labels}}{{$k}}={{$v}}{{println}}{{end}}' \
    | grep -vE '^org\.opencontainers\.image\.(created|revision)=' | sed '/^$/d' | sort > "$OUT/labels.txt" || true

# --- Versões de componentes críticos ----------------------------------------
in_image '
v() {
    local name="$1"; shift
    printf "%-14s " "$name"
    if ! command -v "$1" >/dev/null 2>&1; then echo "não instalado"; return; fi
    local out
    out="$("$@" 2>/dev/null | head -1)"
    [ -z "$out" ] && out="$("$@" 2>&1 | grep -v -i sandbox | head -1)"
    echo "${out:-N/A}"
}
v debian       cat /etc/debian_version
v python       python --version
v chrome       chrome --version
v chromedriver chromedriver --version
v firefox      firefox --version
v geckodriver  geckodriver --version
v java         java -version
v openssl      openssl version
v imagemagick  convert -version
v ghostscript  gs --version
v x11vnc       x11vnc -version
v websockify   bash -c "command -v websockify >/dev/null && pip show websockify | grep ^Version"
v ffmpeg       ffmpeg -version
' | sed -E 's/\(([0-9a-f]{40})[^)]*\)/(\1)/' > "$OUT/versions.txt"

# --- Pacotes ------------------------------------------------------------------
in_image 'pip freeze --all 2>/dev/null | sort -f' > "$OUT/pip-freeze.txt"
in_image "dpkg-query -W -f='\${Package}=\${Version}\n' | sort" > "$OUT/dpkg.txt"

# --- Estrutura de arquivos que formam o "contrato" da imagem ------------------
in_image '
list() { find "$@" 2>/dev/null -printf "%M %u:%g %p\n" | sort -k3; }
echo "## /app (maxdepth 2)"
list /app -maxdepth 2 -not -path "/app/.cache*"
echo
echo "## /opt (maxdepth 1)"
list /opt -maxdepth 1
echo
echo "## /usr/local/bin"
list /usr/local/bin -maxdepth 1
echo
echo "## Chrome policies"
list /etc/opt -maxdepth 4
echo
echo "## Firefox profile"
list /root/.mozilla -maxdepth 3
echo
echo "## Chrome profile (build time)"
list /usr/local/share -maxdepth 1 -name "*rofile*"
' > "$OUT/files.txt"

echo "✅ Snapshot salvo em $OUT"
ls -1 "$OUT"
