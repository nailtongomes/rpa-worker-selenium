# Receita: workers num servidor ARM barato (Oracle Ampere e similares)

Servidores ARM custam menos pelo mesmo número de núcleos: Oracle Cloud (Ampere A1, inclusive na camada
gratuita), Hetzner (CAX), AWS (Graviton), Google Cloud (Axion C4A) e Azure (Cobalt). Para eles existe a
imagem **`ghcr.io/nailtongomes/rpa-worker-selenium:latest-arm64`**: a mesma imagem da `:latest`, com o mesmo
contrato (caminhos, variáveis, entrypoint), compilada para ARM64.

| | `:latest` | `:latest-arm64` |
|---|---|---|
| Arquitetura | amd64 (x86-64) | arm64 (aarch64) |
| Chrome / ChromeDriver | Chrome for Testing `linux64` | Chrome for Testing `linux-arm64` (mesma versão) |
| Firefox / GeckoDriver | `linux-x86_64` | `linux-aarch64` (mesma versão) |
| PJeOffice | pacote oficial (Java 8 da Azul embutido) | mesmo pacote; o Java embutido (só existe para x86-64) é trocado pelo Zulu 8 com JavaFX da Azul para ARM64 |
| Testes antes de publicar | portão completo (`scripts/test-image.sh`) | o mesmo portão, num runner ARM nativo |
| Tags | `latest`, `sha-<7>`, `AAAAMMDD-HHMMSS` | `latest-arm64`, `sha-<7>-arm64`, `AAAAMMDD-HHMMSS-arm64` |

As duas saem do mesmo commit, cada uma só depois de passar no portão na própria arquitetura. O portão
inclui o teste de assinatura do PJeOffice: o Chrome clica em "Testar" na página local do PJeOffice, que pede
a senha, assina com um A1 de teste e devolve nome e CPF. Ou seja, não basta o processo estar vivo.

## 1. Criar o servidor

Qualquer Linux ARM64 com Docker serve. Na Oracle Cloud:

1. *Compute → Instances → Create instance*, imagem **Ubuntu 24.04** (aarch64) e forma **VM.Standard.A1.Flex**
   (Ampere). A camada gratuita tem oferecido até 4 OCPUs e 24 GB de memória no total para Ampere; confira os
   limites atuais da sua conta.
2. Disco de boot com pelo menos 50 GB (a imagem ocupa ~5,4 GB, mais logs e dados).
3. Nenhuma porta de entrada precisa ser aberta além do SSH: o worker só faz conexões de saída.

Tamanho: **1 CPU e 2 GB de memória por worker** (pico medido com PJeOffice ~1,1 GB). Na Ampere, 1 OCPU é
1 núcleo inteiro. Uma VM com 4 OCPUs e 24 GB roda 4 workers com folga.

## 2. Instalar o Docker e baixar a imagem

No servidor (Ubuntu):

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo usermod -aG docker "$USER" && newgrp docker
```

```bash
uname -m && docker pull ghcr.io/nailtongomes/rpa-worker-selenium:latest-arm64
```

`uname -m` precisa responder `aarch64`. A `:latest` (amd64) também baixa num servidor ARM, mas não roda: use
sempre a `-arm64`.

## 3. Conferir o worker antes de colocar em produção

Browsers, certificado (A1 de teste gerado na hora), Java e o teste de assinatura do PJeOffice:

```bash
docker run --rm --shm-size=1g -m 2g -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_PJEOFFICE=1 \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest-arm64 python /app/preflight.py --a1 self-test
```

O esperado no fim:

```text
✅ Java/PJeOffice lê o .pfx (keytool)
✅ PJeOffice assina com o certificado: botão "Testar" da página local: FULANO DE TESTE | 12345678909 [...]
...
✅ worker pronto
```

Com o seu certificado: grave o `.pfx` e a senha em arquivos (fora do Git) e monte como no
[Docker local](../docker-local/README.md#1-preparar-uma-vez), trocando `--a1 self-test` por
`-e A1_PFX_PATH=... -e A1_PFX_PASSWORD_FILE=...`.

## 4. Vários workers

Os [exemplos de servidor](../../examples/server/README.md) funcionam iguais. Só aponte a imagem ARM:

```bash
export RPA_IMAGE=ghcr.io/nailtongomes/rpa-worker-selenium:latest-arm64
```

```bash
cd examples/server && cp ../../.env.example .env && ./workers.sh start 4
```

Com o compose: `RPA_IMAGE=ghcr.io/nailtongomes/rpa-worker-selenium:latest-arm64 docker compose up -d` na mesma
pasta. Para atualizar: `./workers.sh update 4` (ou `docker compose pull && docker compose up -d`).

## Cuidados

- **IP de datacenter.** O IP da Oracle (e de qualquer nuvem) é de datacenter. Se um tribunal ou o GOV.BR
  bloquear, use a saída pelo PC de um cliente: receita [internet do cliente](../internet-do-cliente/README.md),
  que funciona igual na imagem ARM.
- **Impressão digital do browser.** O agente de usuário do Chrome continua `X11; Linux x86_64` (o Chrome
  congela esse texto em todo Linux), mas `navigator.platform` diz `Linux aarch64`. É um sinal a mais para sites
  com antibot. Se um site específico estranhar o worker ARM, compare com a `:latest` antes de concluir.
- **PJeOffice.** O PJeOffice só é publicado para x86-64. A imagem ARM usa o mesmo programa com o Java da Azul
  para ARM64, e o portão prova que ele abre, lê o A1 e assina. Ainda assim, não é uma combinação suportada
  oficialmente pelo CNJ. Se o PJeOffice for crítico para você, valide o seu fluxo antes de migrar.
- **Fixar versão.** Para não mudar de versão sozinho, use `sha-<7>-arm64` em vez de `latest-arm64` (veja as
  [notas de release](https://github.com/nailtongomes/rpa-worker-selenium/releases)).
