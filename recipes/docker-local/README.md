# Receita: worker no seu computador, vendo o browser

Para desenvolver e depurar um script com o seu certificado A1, assistindo ao browser pelo noVNC.
Precisa só de Docker (Docker Desktop no Windows/macOS, ou Docker no Linux). Depois que o script estiver
bom, ele vai para o PC com o [shutup-and-run](../shutup-and-run/README.md) sem mudar nada.

| Arquivo | Para quê |
|---|---|
| [`compose.yml`](compose.yml) | o worker com 2 GB, Xvfb + OpenBox + PJeOffice, A1 por arquivo, noVNC em `127.0.0.1:6080` |
| [`.env.example`](.env.example) | `SCRIPT_URL` e outras opções |
| [`scripts/abrir_com_a1.py`](scripts/abrir_com_a1.py) | exemplo: abre um site com o certificado no Chrome (UC, em janela) e salva um print |

## 1. Preparar (uma vez)

Nesta pasta, crie `segredos/` com o certificado e a senha. A pasta está no `.gitignore`, assim como `.pfx`, `.p12` e `.env`.

```bash
mkdir -p segredos saida && cp ~/certificados/meu-a1.pfx segredos/a1.pfx
```

```bash
read -rs -p "Senha do certificado: " S && printf '%s' "$S" > segredos/a1-senha.txt && unset S
```

```bash
cp .env.example .env && docker compose pull
```

No Windows (PowerShell), o arquivo da senha sem quebra de linha:
`Set-Content -NoNewline -Path segredos\a1-senha.txt -Value (Read-Host "Senha do certificado")`.

## 2. Testar o certificado e os browsers

```bash
docker compose run --rm worker python /app/preflight.py
```

Termina com `✅ worker pronto` se Chrome, UC e Firefox abrem e apresentam o certificado, o Java do PJeOffice
o lê e as assinaturas `.p7s` e PDF funcionam. Nada sai do seu computador.

## 3. Rodar um script vendo o browser

Coloque o script em `scripts/` e rode com `--service-ports` (publica o noVNC):

```bash
docker compose run --rm --service-ports worker python /scripts/abrir_com_a1.py https://pje.tjrn.jus.br/pje/login.seam
```

Abra <http://127.0.0.1:6080/vnc.html> e clique em Connect. O que o script gravar em `/saida` aparece em `./saida/`.

Para testar como em produção, pela URL (o worker baixa e roda), ponha `SCRIPT_URL` no `.env` e:

```bash
docker compose run --rm --service-ports worker
```

## Dicas

- O noVNC não tem senha: a porta fica só em `127.0.0.1`. Não troque por `0.0.0.0` numa rede que não é sua.
- Para ver o worker como o shutup-and-run vai rodar (1 CPU, 2 GB, sem portas, certificado nos caminhos fixos),
  use [`scripts/run-recipe.py`](../../scripts/run-recipe.py) com a receita do shutup-and-run.
- O modelo de script para tarefas de produção é o [`modelo_tarefa.py`](../shutup-and-run/modelo_tarefa.py).
- Mais sobre o certificado (`.p7s`, PAdES, PJeOffice, cadeia ICP-Brasil): [guia do A1](../../docs/A1_CERTIFICATE_GUIDE.md).
