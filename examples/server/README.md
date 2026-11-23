# Vários workers em um servidor Linux

Dois jeitos de subir **N workers** (padrão: 4) da imagem
`ghcr.io/nailtongomes/rpa-worker-selenium:latest` no mesmo servidor. Os dois fazem a mesma coisa:

| | `docker-compose.yml` | `workers.sh` |
|---|---|---|
| Requer | Docker + plugin Compose | só Docker |
| Nº de workers | fixo no arquivo (copie um bloco para adicionar) | parâmetro: `./workers.sh start 6` |
| Início | todos juntos | escalonado (`START_DELAY`, padrão 15 s) |
| Config por worker | `SCRIPT_URL_NN` / `CHROME_PROFILE_URL_NN` no `.env` | arquivo `workers/rpa-worker-NN.env` |

Cada worker é um container isolado, com Xvfb, OpenBox e PJeOffice próprios, `WORKER_ID` próprio
(`rpa-worker-01`, `rpa-worker-02`...) e dados em `./data/rpa-worker-NN/{db,src,tmp,logs}`.
Os workers reiniciam sozinhos (`restart: always`) e voltam após o reboot do servidor.

## 1. Preparar o servidor (uma vez)

```bash
# Docker (Debian/Ubuntu)
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker

# Copiar esta pasta para o servidor (ou clonar o repositório)
git clone https://github.com/nailtongomes/rpa-worker-selenium.git
cd rpa-worker-selenium/examples/server

# Configuração
cp ../../.env.example .env
nano .env          # SCRIPT_URL e segredos (N3_TOKEN, SENHA_TOKEN_A1, ...)
chmod 600 .env
```

**Dimensionamento:** cada worker usa até 2 GB de RAM e 1 vCPU (`WORKER_MEM_LIMIT`, `WORKER_CPUS`)
e 2 GB de `/dev/shm`. Para 4 workers: ~8 GB de RAM livre, 4 vCPUs e ~10 GB de disco para a imagem.

## 2a. Com Docker Compose

```bash
docker compose up -d                  # sobe os 4 workers
docker compose ps                     # status
docker compose logs -f rpa-worker-02  # logs de um worker
docker stats                          # CPU/RAM ao vivo

docker compose pull && docker compose up -d   # atualizar para a :latest
docker compose restart rpa-worker-03          # reiniciar um worker
docker compose down                           # parar tudo (dados preservados)
```

Script ou profile diferente para um worker, no `.env`:

```dotenv
SCRIPT_URL=https://storage.exemplo.com/scripts/worker.py
SCRIPT_URL_03=https://storage.exemplo.com/scripts/outro-worker.py
CHROME_PROFILE_URL_02=https://storage.exemplo.com/profiles/worker-02.zip
```

Mais workers: copie o bloco `rpa-worker-04` em `docker-compose.yml`, trocando `04` por `05`
nos 4 lugares (nome, `WORKER_ID`, variáveis `_05` e volumes).

## 2b. Com o script `workers.sh` (só Docker)

```bash
./workers.sh start 4      # sobe 4 workers, um a cada 15 s
./workers.sh status       # estado + CPU/RAM
./workers.sh logs 02      # logs do rpa-worker-02
./workers.sh update       # docker pull + recria os workers
./workers.sh stop         # para e remove (dados preservados)
```

Override por worker: crie `workers/rpa-worker-02.env` com as variáveis que mudam
(ex.: `SCRIPT_URL=...`). Ajustes do script via ambiente:

```bash
WORKER_MEM_LIMIT=3g START_DELAY=30 ./workers.sh start 6
RPA_IMAGE=ghcr.io/nailtongomes/rpa-worker-selenium:20250101-120000 ./workers.sh update   # fixar uma versão
```

> O `.env` usado pelo script segue o formato do `docker --env-file`: `CHAVE=valor`,
> sem aspas e sem `export`.

## Dicas de operação

- **Rollback:** troque a tag com `RPA_IMAGE=ghcr.io/nailtongomes/rpa-worker-selenium:<tag>`
  (no `.env` para o compose, no ambiente para o script). As tags `sha-*` e `YYYYMMDD-HHMMSS`
  ficam no GHCR.
- **Ver a tela de um worker:** suba um worker extra de debug com `USE_VNC=1 USE_NOVNC=1`
  e porta `6080` (ver [`docs/VNC_QUICKSTART.md`](../../docs/VNC_QUICKSTART.md)). Não exponha VNC na internet.
- **Logs:** limitados a 3 × 10 MB por worker (rotação do Docker); os logs da automação
  ficam em `./data/rpa-worker-NN/logs`.
- **Segredos:** `.env` e `workers/*.env` nunca vão para o git (já estão no `.gitignore`).
