# Certificado digital A1 na imagem

Este guia mostra como usar um certificado A1 (`.pfx`/`.p12`) nos scripts que rodam na
imagem `ghcr.io/nailtongomes/rpa-worker-selenium`. O A1 serve para entrar em sistemas
judiciais pelo Chrome ou pelo Firefox e para assinar documentos (PDF → `.p7s`).

Resumo:

1. Informe o certificado por **URL** (`A1_PFX_URL`) ou por **arquivo montado** (`A1_PFX_PATH`).
2. Informe a senha por **arquivo** (`A1_PFX_PASSWORD_FILE`, recomendado) ou por variável (`A1_PFX_PASSWORD`).
3. No script, use `/app/a1cert.py`.
4. Antes de usar um certificado novo em produção, rode `python /app/a1_check.py` no servidor.

---

## Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `A1_PFX_URL` | URL do `.pfx`. É baixado com 3 tentativas para `/tmp/a1/a1.pfx` (permissão 600) |
| `A1_PFX_PATH` | Alternativa: caminho de um `.pfx` montado por volume |
| `A1_PFX_PASSWORD_FILE` | Arquivo com a senha (Docker secret ou volume `:ro`). **Tem prioridade** |
| `A1_PFX_PASSWORD` | Senha em variável. Funciona, mas aparece no `docker inspect` |
| `A1_WORK_DIR` | Pasta temporária da biblioteca (padrão `/tmp/a1`) |

A senha nunca é registrada em log nem passada em linha de comando. Para o `pk12util` e o
`keytool`, ela vai em um arquivo temporário com permissão 600, apagado em seguida.

---

## Uso nos scripts (`/app/a1cert.py`)

O entrypoint coloca `/app` no `PYTHONPATH`, então `import a1cert` funciona em qualquer
script (inclusive os baixados de `SCRIPT_URL`).

```python
import a1cert

cert = a1cert.load_from_env()          # A1_PFX_URL/A1_PFX_PATH + senha
print(cert.summary())                  # titular, CPF/CNPJ, emissor, validade, cadeia, formato
if cert.days_left < 30:
    print("certificado vence em", cert.days_left, "dias")

try:
    # Chrome / SeleniumBase: importa no NSS (~/.pki/nssdb) e grava a policy
    # AutoSelectCertificateForUrls (sem diálogo de seleção)
    a1cert.install_chrome(cert, ["https://pje.tjrn.jus.br", "[*.]jus.br"])

    # Firefox: importa no NSS do profile selenium.default-release e liga a seleção automática
    a1cert.install_firefox(cert)

    # ... automação com Selenium/SeleniumBase ...

    # PDF -> .p7s com o PDF embutido (attached, CAdES-BES, SHA-256)
    p7s = a1cert.sign_p7s(cert, "/tmp/peticao.pdf")        # /tmp/peticao.pdf.p7s
    a1cert.verify_p7s(p7s, ca_certs=cert.chain)            # confere com openssl cms

    # Assinatura dentro do próprio PDF (PAdES)
    a1cert.sign_pdf(cert, "/tmp/peticao.pdf", "/tmp/peticao-assinada.pdf")
finally:
    a1cert.uninstall(cert)   # remove do NSS do Chrome e do Firefox, apaga policies e o .pfx baixado
```

Exemplo completo: [`examples/scripts/example_a1_certificate.py`](../examples/scripts/example_a1_certificate.py).

### Funções

| Função | O que faz |
|---|---|
| `load_from_env()` / `load_pfx(path, senha)` | Abre o `.pfx`: AES moderno e legados 3DES/RC2. Senha errada → `A1Error("senha incorreta...")` |
| `cert.summary()`, `cert.cpf`, `cert.cnpj`, `cert.days_left`, `cert.is_valid_now` | Dados do certificado (CPF/CNPJ dos campos ICP-Brasil) |
| `usage_findings(cert)` | Diagnóstico: tamanho da chave, chave corresponde ao certificado, `digitalSignature`/`nonRepudiation`, `clientAuth`, cadeia, ICP-Brasil (cadeia validada até as raízes do ITI) |
| `verify_chain(cert)` | Valida a cadeia até uma raiz oficial da ICP-Brasil (`openssl verify`) e devolve o nome da raiz. Usa as ACs do `.pfx` e as de `/opt/icp-brasil`, então funciona com `.pfx` sem cadeia |
| `icp_brasil_certs(roots_only=False)` | Raízes + ACs oficiais da ICP-Brasil, para usar como `ca_certs` em `verify_p7s`/`verify_pdf` (validar documentos assinados por terceiros) |
| `install_chrome(cert, padrões)` / `uninstall_chrome(cert)` | NSS do Chrome + policy em `/etc/opt/chrome*/policies/managed/auto_select_certificate.json` |
| `install_firefox(cert, profile)` / `uninstall_firefox(cert, profile)` | NSS do profile + `security.default_personal_cert = "Select Automatically"` em `user.js` |
| `sign_p7s(cert, arquivo, attached=True)` / `sign_bytes_p7s(...)` | CMS SignedData com `signing-certificate-v2` (CAdES-BES) |
| `verify_p7s(p7s, content=None, ca_certs=...)` / `p7s_content(p7s)` | Verifica com `openssl cms -verify` e devolve o conteúdo assinado |
| `sign_pdf(cert, entrada, saída)` / `verify_pdf(pdf, ca_certs)` | PAdES básico (endesive) |
| `java_can_read(cert)` / `java_password_problem(cert)` | O Java (PJeOffice) abre o `.pfx`? Se não abrir, diz por quê |
| `export_pfx(cert, destino, nova_senha, legacy=False)` | Regrava o `.pfx` com outra senha ou formato |
| `uninstall(cert)` | Limpeza completa |

O apelido no NSS é `rpa-a1-<fingerprint>`. O CN ICP-Brasil (`NOME:CPF`) tem `:`, que o
NSS interpreta como separador de token, por isso não é usado. As ACs da cadeia entram
como `rpa-a1-<fingerprint>-caN` e saem no `uninstall`. Certificados que já estavam no NSS
com outro apelido não são tocados.

### Cadeia ICP-Brasil (`/opt/icp-brasil`)

A imagem traz as raízes e as ACs intermediárias oficiais da ICP-Brasil, baixadas do
[repositório do ITI](https://acraiz.icpbrasil.gov.br/):

- `raizes.pem`: AC Raiz Brasileira v5, v6, v8 a v13, com fingerprint SHA-256 fixado no
  repositório. Ficam de fora a v1 e a v2, já vencidas, e a v7, que usa um algoritmo pós-quântico
  experimental que o OpenSSL ainda não lê.
- `acs.pem`: todas as ACs do `ACcompactado.zip` do ITI que fecham cadeia até essas raízes.
  O pacote é conferido com o SHA-512 que o ITI publica.

Elas servem **só** para validar certificados e assinaturas. Não entram no trust store do
sistema nem no NSS, e a confiança TLS dos browsers continua a mesma. No `a1_check.py`/`usage_findings`:

| Resultado | Significado |
|---|---|
| ✅ `cadeia válida até a Autoridade Certificadora Raiz Brasileira vN` | A1 ICP-Brasil legítimo |
| ⚠️ `a AC emissora não está entre as ACs oficiais empacotadas` | `.pfx` sem a cadeia e com AC que não está no pacote: AC nova (atualize a imagem) ou certificado falso |
| ❌ `diz ser ICP-Brasil mas a cadeia não fecha` | raiz que não é do ITI, assinatura inválida ou AC vencida |

Para validar um `.p7s` recebido de terceiros:

```python
a1cert.verify_p7s("documento.pdf.p7s", ca_certs=a1cert.icp_brasil_certs())
```

O nightly compara o pacote com o ITI todo dia e falha se surgir uma AC nova. Para
atualizar, rode `scripts/update-icp-brasil.py` e abra um PR.

### Padrões de URL da policy do Chrome

`install_chrome` aceita padrões no formato do Chrome:
`https://pje.tjrn.jus.br`, `https://[*.]tjrn.jus.br`, `[*.]jus.br` ou `*`. O filtro usa o
**emissor** do certificado (`ISSUER.CN`). Assim, se houver mais de um A1 no NSS, o Chrome
escolhe o certo para a AC.

---

## Verificar um certificado no servidor (`/app/a1_check.py`)

Rode no servidor onde os workers vão usar o certificado. Nada sai do container: o
teste de browser usa um servidor HTTPS **local** que exige certificado de cliente.

```bash
printf '%s' 'senha-do-certificado' > a1-senha.txt && chmod 600 a1-senha.txt
docker run --rm --shm-size=2g -e USE_XVFB=1 -e USE_OPENBOX=1 \
  -e A1_PFX_URL="https://exemplo.com/certificados/a1.pfx" \
  -e A1_PFX_PASSWORD_FILE=/run/secrets/a1 -v "$PWD/a1-senha.txt:/run/secrets/a1:ro" \
  -v "$PWD/a1-check:/out" \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest \
  python /app/a1_check.py --out /out --json /out/a1-check.json
```

Saída típica:

```
🔐 Verificação do certificado A1

✅ certificado aberto: FULANO DE TAL:12345678909 | emissor: AC ... | formato: PBES2
✅ identificação ICP-Brasil: CPF 12345678909
✅ validade: 287 dias restantes (2027-09-05T...)
✅ chave: RSA 2048 bits
✅ uso da chave: digitalSignature + nonRepudiation
✅ uso estendido: clientAuth (login em sites com certificado)
✅ cadeia: 3 AC(s) até a raiz: ...
✅ ICP-Brasil: emitido na hierarquia ICP-Brasil
✅ PDF → .p7s attached (CAdES-BES): /out/documento.pdf.p7s — assinatura e cadeia verificadas com openssl cms
✅ PDF assinado (PAdES): /out/documento-assinado.pdf
✅ Java/PJeOffice lê o .pfx (keytool)
✅ Chrome: importado no NSS + policy AutoSelectCertificateForUrls
✅ Chrome (Selenium) apresenta o certificado [janela no :99]: FULANO DE TAL:12345678909
✅ Chrome (SeleniumBase UC) apresenta o certificado [janela no :99]: FULANO DE TAL:12345678909
✅ Firefox: importado no NSS do profile (cópia de selenium.default-release)
✅ Firefox apresenta o certificado [janela no :99]: FULANO DE TAL:12345678909
✅ limpeza: certificado removido do NSS e policies apagadas

✅ ambiente pronto para o certificado A1
```

O comando sai com exit 0 se tudo passar e 1 se algo falhar (⚠️ não reprova), então
serve como verificação prévia num fluxo do Kestra.

| Opção | Uso |
|---|---|
| `--pdf ARQUIVO` | assina um PDF seu em vez do de exemplo |
| `--out DIR` | onde gravar `.p7s` e PDF assinado (padrão `/tmp/a1-check`) |
| `--json ARQUIVO` | resultado estruturado (`ok`, `falhas`, `avisos`, `certificado`, `passos`) |
| `--browsers chrome,uc,firefox` | quais browsers testar |
| `--warn-days N` | avisa quando faltar menos de N dias para vencer (padrão 30) |
| `--keep` | não remove o certificado do NSS ao final |
| `--self-test` | usa uma ICP de teste (não precisa de certificado) |

> O certificado real **não vai para o GitHub**, nem em secrets. No CI, a mesma cadeia de
> verificações roda com uma ICP de teste (`/app/a1_testkit.py`) em
> `tests/image/test_a1_certificate.py`, a cada PR, release e build noturno.

---

## Problemas conhecidos (e o que os testes antecipam)

| Sintoma | Causa | O que fazer |
|---|---|---|
| PJeOffice não abre o certificado; `a1_check` mostra "fora do ASCII" | O Java não abre `.pfx` com senha acentuada ou com `ç` | Regrave com uma senha ASCII: `a1cert.export_pfx(cert, "/tmp/novo.pfx", "nova-senha")` |
| `senha incorreta ou arquivo .pfx inválido` | senha errada, arquivo corrompido ou baixado pela metade (HTML de erro no lugar do `.pfx`) | confira a URL com `curl -I` e a senha |
| `.pfx` antigo (RC2-40/3DES) | formato legado, que o OpenSSL 3 recusa sem o provider `legacy` | já suportado na imagem (Python, NSS e Java); testado no portão |
| ⚠️ cadeia: "o .pfx não traz as ACs" | exportado sem a cadeia | os browsers locais funcionam; se um site recusar, exporte novamente com a cadeia |
| Chrome abre o diálogo de seleção | sem policy para aquele site, ou mais de um certificado da mesma AC | `install_chrome(cert, [padrão do site])`; mantenha um A1 por container |
| Firefox pede para escolher o certificado | o profile usado não é o que recebeu o certificado | use `install_firefox(cert, <profile que o driver usa>)` |
| Certificado vencido | `cert.is_valid_now` é falso | `a1_check` reprova; renove o certificado |

---

## Como funciona por dentro

```
.pfx (URL/arquivo) + senha
   │  cryptography.load_pkcs12 (AES, 3DES, RC2)
   ▼
A1Certificate ──► pk12util (re-export AES, apelido estável) ──► NSS ~/.pki/nssdb ──► Chrome / SeleniumBase UC
   │                                                     └────► NSS do profile ─────► Firefox
   │            policy AutoSelectCertificateForUrls ─────────────────────────────────► Chrome (sem diálogo)
   ├──► endesive + asn1crypto ──► .p7s attached/detached (CAdES-BES) ──► openssl cms -verify
   ├──► endesive.pdf ───────────► PDF assinado (PAdES)
   └──► keytool ───────────────► Java/PJeOffice
```

Veja também [`CA_RUNTIME_MANAGEMENT.md`](CA_RUNTIME_MANAGEMENT.md), sobre instalar ACs
(por exemplo, as raízes ICP-Brasil) em tempo de execução.
