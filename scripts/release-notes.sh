#!/bin/bash
# =============================================================================
# Notas do GitHub Release de uma imagem publicada (usado por build-push-ghcr.yml).
#
# Escreve Markdown no stdout: imagem/digest, como voltar para a versão anterior
# (rollback), PRs/commits desde a imagem anterior, mudanças de versões dentro da
# imagem e o resumo do portão de qualidade.
#
# Variáveis (só IMAGE_NAME, DIGEST e SHORT_SHA são obrigatórias):
#   IMAGE_NAME      ghcr.io/dono/repo
#   DIGEST          sha256:... da imagem publicada
#   SHORT_SHA       7 primeiros caracteres do commit publicado
#   TIMESTAMP       tag de data publicada (YYYYMMDD-HHMMSS)
#   HEAD_SHA        commit publicado (padrão: HEAD)
#   PREV_REVISION   commit da :latest anterior (label org.opencontainers.image.revision)
#   PREV_DIGEST     digest da :latest anterior
#   SNAP_CURRENT    snapshot (scripts/image-snapshot.sh) da :latest anterior
#   SNAP_CANDIDATE  snapshot da imagem publicada
#   GATE_SUMMARY    test-results/summary.md do portão
# =============================================================================
set -euo pipefail

: "${IMAGE_NAME:?}" "${DIGEST:?}" "${SHORT_SHA:?}"
HEAD_SHA="${HEAD_SHA:-$(git rev-parse HEAD)}"
PREV_REVISION="${PREV_REVISION:-}"
PREV_DIGEST="${PREV_DIGEST:-}"
TIMESTAMP="${TIMESTAMP:-}"

echo "## 📦 Imagem"
echo ""
echo "- \`${IMAGE_NAME}:latest\` → \`${DIGEST}\`"
echo "- Tags: \`latest\`, \`sha-${SHORT_SHA}\`${TIMESTAMP:+, \`${TIMESTAMP}\`}"
echo "- Commit: ${HEAD_SHA}"
echo ""
echo '```bash'
echo "docker pull ${IMAGE_NAME}@${DIGEST}"
echo '```'
echo ""

echo "## ↩️ Rollback"
echo ""
if [ -n "${PREV_REVISION}" ]; then
    prev_tag="sha-${PREV_REVISION:0:7}"
    echo "Versão anterior em produção: \`${prev_tag}\`${PREV_DIGEST:+ (\`${PREV_DIGEST}\`)}."
    echo ""
    echo '```bash'
    echo "# só neste servidor: fixe a versão anterior no compose/docker run"
    echo "docker pull ${IMAGE_NAME}:${prev_tag}"
    if [ -n "${PREV_DIGEST}" ]; then
        echo "#   image: ${IMAGE_NAME}@${PREV_DIGEST}"
    fi
    echo ""
    echo "# para todos: aponte a :latest de volta para a versão anterior (exige login com write:packages)"
    echo "docker buildx imagetools create -t ${IMAGE_NAME}:latest ${IMAGE_NAME}:${prev_tag}"
    echo '```'
    echo ""
    echo "> O GHCR guarda só as 5 tags mais recentes: a \`${prev_tag}\` some depois de 5 novos releases."
else
    echo "Sem informação da versão anterior (a \`:latest\` anterior não tinha o label de revisão)."
fi
echo ""

echo "## 📝 Mudanças"
echo ""
range="${HEAD_SHA}"
if [ -n "${PREV_REVISION}" ] && git merge-base --is-ancestor "${PREV_REVISION}" "${HEAD_SHA}" 2>/dev/null; then
    range="${PREV_REVISION}..${HEAD_SHA}"
    echo "Desde \`sha-${PREV_REVISION:0:7}\` ([diff completo](https://github.com/${GITHUB_REPOSITORY:-}/compare/${PREV_REVISION}...${HEAD_SHA})):"
else
    echo "Últimos commits (versão anterior desconhecida ou fora do histórico):"
fi
echo ""
count=0
# --first-parent: um item por PR mesclado na main (e commits diretos)
while IFS=$'\t' read -r sha subject body; do
    count=$((count + 1))
    if [[ "${subject}" =~ ^Merge\ pull\ request\ (#[0-9]+) ]]; then
        echo "- ${BASH_REMATCH[1]} ${body:-${subject}}"
    else
        echo "- ${subject} (${sha})"
    fi
done < <(git log --first-parent --max-count=50 --format='%h%x09%s%x09%b' "${range}" | grep -v '^$' | awk -F'\t' 'NF>=2')
if [ "${count}" -eq 0 ]; then
    echo "- (nenhum commit novo: rebuild com atualizações do Debian/PyPI)"
fi
echo ""

if [ -n "${SNAP_CURRENT:-}" ] && [ -d "${SNAP_CURRENT}" ] && [ -n "${SNAP_CANDIDATE:-}" ] && [ -d "${SNAP_CANDIDATE}" ]; then
    echo "## 🔍 O que mudou dentro da imagem"
    echo ""
    echo '```diff'
    diff -u "${SNAP_CURRENT}/versions.txt" "${SNAP_CANDIDATE}/versions.txt" | grep '^[-+][^-+]' || echo "(versões de browsers/drivers iguais)"
    diff -u "${SNAP_CURRENT}/pip-freeze.txt" "${SNAP_CANDIDATE}/pip-freeze.txt" | grep '^[-+][^-+]' || echo "(pip freeze igual)"
    echo "dpkg: $(diff "${SNAP_CURRENT}/dpkg.txt" "${SNAP_CANDIDATE}/dpkg.txt" | grep -c '^>' || true) pacote(s) alterado(s)"
    echo '```'
    echo ""
fi

if [ -n "${GATE_SUMMARY:-}" ] && [ -s "${GATE_SUMMARY}" ]; then
    echo "<details><summary>🧪 Portão de qualidade (scripts/test-image.sh)</summary>"
    echo ""
    cat "${GATE_SUMMARY}"
    echo ""
    echo "</details>"
fi
