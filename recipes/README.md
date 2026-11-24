# Receitas plug and play

Cada receita é uma pasta com arquivos prontos para copiar e um passo a passo curto.
Você troca só o que está marcado (URL do script, certificado, senhas) e roda.

| Quero... | Receita | Onde roda |
|---|---|---|
| Testar meu certificado A1 e os browsers no PC, sem escrever script | [shutup-and-run: teste do A1](shutup-and-run/README.md#1-testar-o-certificado-a1-no-pc) | PC com o [shutup-and-run](https://github.com/nailtongomes/shutup-and-run) |
| Rodar uma rotina no PC de tempos em tempos, sem orquestrador | [shutup-and-run: rotina](shutup-and-run/README.md#2-rotina-no-pc-sem-orquestrador) | PC com o shutup-and-run |
| Cadastrar tarefas na nuvem (orquestrador, API, IA) e executar no PC | [shutup-and-run: tarefa por poll](shutup-and-run/README.md#3-tarefas-vindas-do-orquestrador-na-nuvem-ou-de-uma-ia) | nuvem + PC com o shutup-and-run |
| Desenvolver ou depurar um script vendo o browser | [Docker local](docker-local/README.md) | seu computador com Docker |
| Rodar na VPS, mas sair pela internet (IP residencial) do PC do cliente | [internet do cliente](internet-do-cliente/README.md) | VPS + PC com o shutup-and-run |
| Vários workers num servidor | [`examples/server/`](../examples/server/README.md) | servidor Linux |
| Workers num servidor ARM barato (Oracle Ampere, Hetzner CAX, Graviton) | [servidor ARM](servidor-arm/README.md) | servidor Linux ARM64 |
| Worker aguardando tarefas por HTTP (standby) | [`examples/compose/`](../examples/compose/docker-compose.standby.yml), [docs/WORKER.md](../docs/WORKER.md) | servidor |
| Saída por um relay/proxy próprio (SOCKS5/HTTP) | [docs/EGRESS_RELAY.md](../docs/EGRESS_RELAY.md) | qualquer lugar |

## O que vale para todas

- **Imagem:** `ghcr.io/nailtongomes/rpa-worker-selenium:latest` (Chrome, Firefox, SeleniumBase UC, PJeOffice,
  certificado A1 dinâmico). Em servidor ARM64, `:latest-arm64` ([servidor ARM](servidor-arm/README.md)).
  Para fixar uma versão, use a tag `sha-<commit>` (`sha-<commit>-arm64`) ou o digest das
  [notas de release](https://github.com/nailtongomes/rpa-worker-selenium/releases).
- **Tamanho:** 2 GB de memória e 1 GB de `/dev/shm` por worker. O pico medido com PJeOffice ligado foi
  ~1,1 GB; 2 GB é também o limite padrão por tarefa do shutup-and-run num PC compartilhado.
  A imagem ocupa ~5,4 GB no disco (o primeiro download demora).
- **Furtividade:** `USE_XVFB=1` + `USE_OPENBOX=1` e o browser em janela (`Driver(uc=True, headless=False)`),
  como em produção. Headless é mais fácil de ser marcado como bot.
- **Certificado A1:** sempre `A1_PFX_PATH` (ou `A1_PFX_URL`) + `A1_PFX_PASSWORD_FILE`. A senha fica num arquivo,
  nunca numa variável ou na linha de comando. No script: `cert = a1cert.load_from_env()`
  ([guia do A1](../docs/A1_CERTIFICATE_GUIDE.md)).
- **Antes de produção:** `python /app/preflight.py` diz se browsers, A1 e relay estão funcionando, num JSON só.
  Com o PJeOffice ligado (`USE_PJEOFFICE=1`), inclui o teste de assinatura dele (`/app/pjeoffice_check.py`).
- **Logs:** URLs com token (`SCRIPT_URL`, `HELPER_URLS`) saem mascaradas nos logs da imagem.

## Testar uma receita do shutup-and-run sem instalar o shutup-and-run

[`scripts/run-recipe.py`](../scripts/run-recipe.py) roda a definição com o Docker deste computador do mesmo jeito
que o shutup-and-run rodaria: mesmos limites (1 CPU, 2 GB sem swap), `--init`, sem portas, e o certificado
repassado nos mesmos caminhos fixos. É o que o portão de qualidade usa para provar que a receita de
teste do A1 funciona a cada release.

```bash
scripts/run-recipe.py recipes/shutup-and-run/teste-a1.json --pfx ~/certificados/meu-a1.pfx --password-file ~/certificados/senha.txt
```
