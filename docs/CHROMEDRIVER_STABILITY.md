# Estabilidade do ChromeDriver: investigação e testes

Sintoma em produção (SeleniumBase + Chrome, containers de 2 GB, servidor com 8 vCPUs e 32 GB): o browser
abre, autentica e navega, mas depois de um tempo os comandos falham com

```
HTTPConnectionPool(host='localhost', port=46449): Max retries exceeded ...
Failed to establish a new connection: [Errno 111] Connection refused
```

em portas diferentes a cada sessão, muitas vezes **cerca de 60 s depois de uma navegação**, sem OOM nem
segfault no kernel.

## Resumo

**Causa encontrada e reproduzida (100% das tentativas, headless e headful):** a partir do **SeleniumBase
4.58.0** (15/11/2026), o modo UC (`Driver(uc=True)`, `SB(uc=True)`) perde a sessão quando `driver.get()` abre uma
página que responde **4xx/5xx** ou que contém **reCAPTCHA** (comum em sistemas judiciais), desde que a aba já
esteja numa página http. O erro aparece **~62 s depois**, no comando seguinte, exatamente com a mensagem acima.

Não é memória, versão do Chrome/ChromeDriver nem o patch `cdc_` do ChromeDriver (detalhes abaixo).

**Correção na imagem** (sem mudar os scripts): policy gerenciada do Chrome que permite pop-ups
(`/etc/opt/chrome*/policies/managed/popups.json`), o comportamento de antes da 4.58.

**Contorno para quem ainda usa a imagem atual:** no script, `Driver(uc=True, chromium_arg="--disable-popup-blocking")`
(ou `SB(uc=True, chromium_arg=...)`). Não há tag antiga para rollback: todas as tags que o GHCR ainda guarda (desde 23/11)
já têm SeleniumBase 4.58.x.

> Reproduzido com scripts sintéticos no modo UC. Se algum script de produção **não** usa `uc=True`, esta não
> é a causa dele: rode `python /app/browser_stability.py` no servidor (abaixo) e mande o diagnóstico.

## Como a sessão morre (passo a passo, com o log do ChromeDriver)

1. No modo UC, `driver.get(url)` é trocado por `uc_special_open_if_cf`: o Python baixa a URL com `requests`
   (timeout 1,25 s) e, se a resposta for 3xx/4xx/5xx **final** ou tiver marcas de captcha (`com/recaptcha/api.js`,
   `<title>403 Forbidden</title>`, Cloudflare...), abre a página "especial":
   `with driver: driver.execute_script('window.open(url, "_blank")'); driver.close()`.
2. O SeleniumBase 4.58.0 removeu `--disable-popup-blocking` do modo UC ("Option might not be needed anymore.
   Removing for now."). No modo UC é o SeleniumBase que inicia o Chrome (o ChromeDriver, que sempre passa esse flag,
   só se conecta depois). Com o bloqueador ativo, o `window.open()` sem gesto do usuário volta `null`. O log mostra:
   `ExecuteScript window.open(...) -> null`, e o `Target.getTargets` seguinte só traz `chrome://omnibox-popup`.
3. `driver.close()` fecha a **única** aba.
4. O `with driver:` termina com `reconnect()`: ele para o ChromeDriver, sobe outro **na mesma porta** e chama
   `start_session()`. O ChromeDriver novo procura uma aba no Chrome (`/json/list` → `[]`) por **60 s** e desiste:
   `session not created: cannot connect to chrome at 127.0.0.1:9222 from unknown error: unable to discover open pages`.
5. O Selenium, ao falhar o `start_session`, chama `service.stop()`: o ChromeDriver novo sai (exit 0).
6. O `reconnect()` engole todas as exceções (`with suppress(Exception)`), então `driver.get()` "funciona". O
   **próximo comando** (no próprio SeleniumBase, `driver.window_handles`) vai para a porta sem ninguém:
   `Connection refused`. Em headful, o Chrome sem janelas ainda encerra.

### Bisseção do SeleniumBase (mesma imagem, Chrome 158.0.8127.36, `--network none`, sequencial)

| SeleniumBase | resultado |
|---|---|
| 4.30.0, 4.40.0, 4.48.4, 4.50.0, 4.52.0, 4.55.0, 4.57.0, 4.57.1 | ✅ |
| 4.58.0, 4.58.1, 4.58.2, 4.58.3, 4.58.4, 4.59.0, 4.59.1 | ❌ `Connection refused` ~62 s depois |

O diff 4.57.1 → 4.58.0 só tem uma mudança no modo UC que afeta isso: a linha do `--disable-popup-blocking` comentada.
As duas correções foram confirmadas na 4.59.0: `chromium_arg="--disable-popup-blocking"` e a policy
`DefaultPopupsSetting: 1`.

Uma primeira rodada com containers em paralelo e `--network host` deu falso positivo em 4.57.1: no modo UC o
SeleniumBase usa a porta 9222 se ela estiver livre **no host**. Fica o aviso para quem roda vários workers com
`--network host`: eles disputam essa porta.

## Hipóteses investigadas

| Hipótese | Evidência | Conclusão |
|---|---|---|
| Falta de memória / OOM | Pico de 324–601 MB por container de 2 GB nos testes (3 simultâneos, com e sem PJeOffice); `memory.events` com `oom_kill 0` em todas as falhas reproduzidas | descartada para este sintoma; o diagnóstico registra OOM em qualquer falha |
| Chrome x ChromeDriver incompatíveis | Ambos 158.0.8127.36 (Chrome for Testing); a falha também ocorre com o ChromeDriver oficial sem patch | descartada |
| Patch `cdc_` corrompe o ChromeDriver | Binário com o mesmo tamanho (29.047.520 bytes) e as mesmas seções ELF do oficial; só 520 bytes diferem (20 ocorrências × 26 bytes, todas dentro das strings `cdc_`); falha idêntica com o binário oficial | descartada |
| Selenium/SeleniumBase atualizados sozinhos | `pip install --upgrade seleniumbase` a cada release; a regressão entrou na 4.58.0 e foi para a `:latest` sem nenhum commit aqui | **causa** (agora fixo) |
| ChromeDriver do PATH ≠ usado pelo SeleniumBase | UC: `seleniumbase/drivers/uc_driver` (cópia do da imagem). `Driver()` não-UC **com internet**: baixava o ChromeDriver mais novo da versão (158.0.8127.88, sem patch) a cada container; sem internet, caía no `/usr/local/bin/chromedriver` depois de 2 tentativas | não causa a falha, mas o binário variava com a rede: corrigido (abaixo) |
| Entrypoint mata o ChromeDriver | Só há `kill` em `cleanup_iteration` (entre iterações do loop) e no timeout da iteração/standby (`WORKER_TIMEOUT`) | descartada |
| Condição de corrida | Porta 9222 do UC com `--network host` (acima); reconexão do UC reutiliza a mesma porta e engole falhas | registrada; o diagnóstico mostra PID, porta e exit code |
| `/dev/shm` | O SeleniumBase passa `--disable-dev-shm-usage` no Linux; uso de shm 0 MB nas falhas | descartada (o preflight já avisa shm pequeno) |
| Limite de PIDs / zombies | O UC deixa um ChromeDriver zombie (sem `wait()`) por reconexão, filho do processo do script; dezenas por execução, longe de `pids.max` | não causa a falha; contado e registrado no relatório |
| PJeOffice / JVM | +~175 MB no pico (RSS da JVM ~118 MB) com 2 GB; sem degradação de tempo (1,0x) | descartada |
| DNS / TCP / TLS | Falhas de rede viram página de erro do Chrome (`ERR_*`), não `Connection refused` na porta local; o teste classifica cada uma | descartada |

## Outros achados (corrigidos neste PR)

- **ChromeDriver baixado em tempo de execução:** sem `seleniumbase/drivers/chromedriver`, o `Driver()` não-UC baixava
  um ChromeDriver diferente do da imagem toda vez que um container novo tinha internet: 1 a 3 s a mais, outra versão e
  sem o patch. Agora o ChromeDriver da imagem está lá.
- **`Driver(uc=True, cft=True)`:** o SeleniumBase baixava o Chrome for Testing **mais novo** (~440 MB, outra versão
  que a da imagem) na primeira chamada de cada container. No ARM64, ele procurava `chrome-linux64`, mas o download
  extraía `chrome-linux-arm64`, então baixava de novo a cada partida. Agora `cft_drivers/chrome-linux64` aponta para
  `/opt/chrome`, que já é o Chrome for Testing do `CHROME_VERSION`.
- Todas as cópias do ChromeDriver (`chromedriver`, `uc_driver` e as duas em `cft_drivers/`) são **um arquivo só**
  (hard links na mesma camada). O build confere byte a byte com `/usr/local/bin/chromedriver`. Custo em tamanho: zero
  (antes já havia uma cópia em `uc_driver`).
- **example.com/example.org** pedem, na própria página, para não serem usados em testes e monitoramento. Os testes
  externos usam as páginas de teste do projeto Selenium e o httpbingo ("HTTP Client Testing Service").

## Testes de estabilidade (`/app/browser_stability.py`)

Roda dentro da imagem: no portão de qualidade e no servidor de produção. Os cenários locais usam um servidor HTTP
dentro do próprio processo e são determinísticos, sem internet.

| Cenário | O que faz |
|---|---|
| `sequencial` | uma sessão, 3 rodadas por 5 páginas: título, URL final, conteúdo, formulário, JavaScript e ChromeDriver vivo (`/status`) |
| `sessoes` | 5 sessões criadas, usadas e fechadas; processos do browser vivos 10 s depois do `quit()` reprovam |
| `prolongada` | uma sessão por `--duration` s (120 no portão), alternando navegação, espera e JavaScript; amostra memória e processos do Chrome |
| `recuperacao` | página lenta e travada (timeout de carregamento), conexão cortada, 500, 503 e 3 redirecionamentos; depois de cada uma: driver vivo, sessão válida, nova navegação e JavaScript |
| `uc_especial` | a regressão acima: UC abrindo 503, reCAPTCHA e 403 entre páginas normais |
| `modos` | Selenium, SeleniumBase, UC e UC + `cft=True`, headless e headful: registra caminho, sha256 e versão do ChromeDriver e do Chrome usados |
| `externos` | (`--external`) 5 páginas públicas feitas para teste, 1 rodada, 1 s entre elas; configurável em `STABILITY_EXTERNAL_URLS` (`url\|texto esperado\|fim da URL final`) |

**Classes de falha:**
- **Rede ou site:** `DNS_ERROR`, `TCP_CONNECTION_ERROR`, `TLS_ERROR`, `HTTP_ERROR`, `NAVIGATION_TIMEOUT`,
  `CONTENT_MISMATCH`.
- **Browser:** `CHROME_CRASH`, `CHROMEDRIVER_EXITED`, `WEBDRIVER_CONNECTION_REFUSED`, `SESSION_LOST`,
  `RESOURCE_EXHAUSTED`.

`Connection refused` vira `CHROMEDRIVER_EXITED` quando ninguém mais escuta na porta do driver, e
`WEBDRIVER_CONNECTION_REFUSED` quando o processo ainda existe. Um OOM no cgroup sempre vira `RESOURCE_EXHAUSTED`.
Num site externo, falha de rede ou de site é **aviso**; falha do browser **sempre reprova**.

**Nada é repetido:** a primeira falha fica registrada como aconteceu.

**Em cada falha**, `<out>/<label>/falhas/<cenário>-<n>-<classe>/` guarda:
- `diag.json`, com versões, binário e sha256 do driver, PID, porta, exit code e `/status` do ChromeDriver, processos
  do Chrome, zombies, maiores RSS, cgroup (`memory.current/peak/max`, `memory.events`, PIDs, CPU), `/dev/shm`, Xvfb e
  PJeOffice;
- `traceback.txt`;
- `screenshot.png` e `console.json` (se a sessão ainda responder);
- `chromedriver.log`, o log `--verbose` do ChromeDriver com `SE_DEBUG`.

Logs de cenário que passou são apagados. URLs aparecem sem usuário, senha ou query string.

### No portão (`scripts/test-image.sh`, amd64 e arm64)

1. **Container sozinho** (2 GB, 1 CPU, shm 2 GB, `--init`, Xvfb):
   - `sequencial` + `uc_especial` em `uc-headful`;
   - `externos` quando `RUN_ONLINE_TESTS=1`.
2. **Três containers ao mesmo tempo**, com os mesmos limites:
   - **sem PJeOffice e com PJeOffice:** só isso muda entre os dois; rodam `modos`, `sequencial`, `sessoes`,
     `recuperacao` e `uc_especial` em `uc-headful`;
   - **sessão prolongada** de 120 s em `uc-headless`.

O resultado sai numa tabela no resumo do job: resultado, navegações, mediana, pico de memória e limite, OOM kill,
zombies e RSS do PJeOffice. A degradação (mediana com 3 simultâneos ÷ sozinho) acima de 3x só gera aviso.

Na máquina de desenvolvimento, as duas etapas levaram **2 min 31 s**. Os relatórios ficam em `test-results/stability/`,
nos artefatos do GitHub Actions.

Contra a `:latest` atual (sem a correção), o portão **reprova** com `CHROMEDRIVER_EXITED` em `/status/503` depois de
62,4 s, com o log do ChromeDriver mostrando `unable to discover open pages`. Com a correção, passa.

## Versões: fixas, com canário

- `ARG SELENIUMBASE_VERSION=4.59.0` no Dockerfile, a versão que já estava em produção. Ela é instalada num segundo
  `pip install`, depois do `requirements.txt`, como o `--upgrade` antigo. Num pip só daria `ResolutionImpossible`: o
  `requirements.txt` fixa `psutil==6.1.0`, que o SeleniumBase novo recusa. O resultado é igual ao de produção
  (SeleniumBase 4.59.0, Selenium 4.54.0, psutil 7.2.2) e o `pip check` fica limpo. O SeleniumBase fixa o Selenium.
- **Canário:** todo dia, o job `seleniumbase-canary` do nightly constrói a imagem igual à do release com
  `SELENIUMBASE_VERSION=latest` e roda o `browser_stability.py` com os limites de produção.
  - **Verde:** suba o ARG num PR, que passa pelo portão completo.
  - **Vermelho:** não promova.
- `/app/image_info.json` e a primeira linha do log mostram as versões do Selenium e do SeleniumBase. As notas do
  release já trazem o diff do `pip freeze`.
- **Rollback:** tags `sha-<7>` (GitHub Release) ou um build com `--build-arg SELENIUMBASE_VERSION=<versão anterior>`.
- `SELENIUMBASE_VERSION=latest` volta ao comportamento antigo (`pip install --upgrade seleniumbase`).

## Riscos e limitações

- **Pop-ups liberados para todos os sites** (policy gerenciada). Fora do modo UC nada muda, porque o ChromeDriver já
  inicia o Chrome com `--disable-popup-blocking`. Quem precisar do bloqueador pode apagar
  `/etc/opt/chrome*/policies/managed/popups.json` no container. Com policy, o Chrome headful mostra "gerenciado pela
  organização" no menu; isso não é visível para sites. O A1 já usava policy.
- **Nem todo `Connection refused` é este.** Ele também aparece se o script chama o driver depois de `quit()`, se outro
  processo mata o ChromeDriver ou com `driver.disconnect()` do UC. O diagnóstico distingue pelo PID, pela porta e pelo
  exit code.
- **Problema que continua no SeleniumBase:** o `reconnect()` do UC engole qualquer falha e deixa um zombie por
  reconexão. Vale abrir uma issue no SeleniumBase com a reprodução acima.
- **Sites externos** podem mudar ou cair: falha de rede ou de site não reprova, e a lista é configurável.
- **Limites do ambiente de teste:** no ambiente desta investigação (sem internet direta) os cenários externos rodaram
  por proxy. O portão do CI roda com internet.

## Reproduzir

No servidor, com a imagem que está em produção e os limites do worker:

```bash
docker run --rm --memory=2g --cpus=1 --shm-size=2g --init -e USE_XVFB=1 -e USE_OPENBOX=1 \
  -v "$PWD/estabilidade:/app/logs/stability" ghcr.io/nailtongomes/rpa-worker-selenium:latest \
  python /app/browser_stability.py --mode uc-headful --external
```

Com a imagem atual (antes deste PR), use `-v .../browser_stability.py:/app/browser_stability.py:ro` com o arquivo deste
repositório. Outras opções:
- `--scenarios prolongada --duration 900`: uma sessão longa;
- `-e USE_PJEOFFICE=1`: com o PJeOffice;
- `--modes selenium-headless,uc-headless,uccft-headless`.

Reprodução mínima do bug, no modo UC e sem internet:

```python
from seleniumbase import Driver
d = Driver(uc=True, headless=True)
d.get("http://127.0.0.1:8000/qualquer")       # página 200
d.get("http://127.0.0.1:8000/responde-503")   # ~62 s depois: MaxRetryError ... Connection refused
```

Localmente, no portão:

```bash
scripts/test-image.sh rpa-worker:local
```

```bash
RUN_ONLINE_TESTS=0 scripts/test-image.sh rpa-worker:local
```
