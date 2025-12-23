# Guia Rápido: Workers Docker Compose (PT-BR)

Este guia explica como configurar workers distribuídos para executar RPAs pesadas com reinicialização automática.

## 📋 Requisitos

- Docker e Docker Compose instalados
- Mínimo 2 vCPUs e 8GB RAM (recomendado para 2 workers)
- VPS (ex: Hostinger, DigitalOcean, AWS, etc.)

## 🚀 Início Rápido

### 1. Clone o Repositório

```bash
git clone https://github.com/nailtongomes/rpa-worker-selenium.git
cd rpa-worker-selenium
```

### 2. Crie os Diretórios Necessários

```bash
mkdir -p app/src app/db app/tmp app/logs
```

### 3. Coloque Seus Scripts RPA

Copie seus scripts Python para o diretório `app/src/`:

```bash
cp seu_script_rpa.py app/src/
```

### 4. Configure as Variáveis de Ambiente

Copie o arquivo de exemplo e edite conforme necessário:

```bash
cp .env.example .env
nano .env  # ou use seu editor preferido
```

Exemplo de configuração:

```bash
# Nome do script a executar (deve estar em app/src/)
SCRIPT_NAME=seu_script_rpa.py

# Máximo de horas antes de forçar reinício (padrão: 3)
MAX_RUN_HOURS=3

# Desabilitar display virtual para melhor performance (padrão)
USE_XVFB=0
USE_OPENBOX=0
USE_VNC=0
```

### 5. Inicie os Workers

Para uma VPS com 2 vCPUs e 8GB RAM (como Hostinger), recomenda-se 2 workers:

```bash
# Iniciar 2 workers
docker compose -f docker-compose.worker.yml up -d --scale rpa-worker=2

# Ver logs em tempo real
docker compose -f docker-compose.worker.yml logs -f

# Verificar status
docker compose -f docker-compose.worker.yml ps
```

## 🎯 Funcionamento

### Arquitetura

```
┌──────────────────────────────────────────────────┐
│           VPS (2 vCPU / 8GB RAM)                 │
├──────────────────────────────────────────────────┤
│                                                   │
│  ┌────────────────┐      ┌────────────────┐     │
│  │  Worker #1     │      │  Worker #2     │     │
│  │  CPU: 1.0 max  │      │  CPU: 1.0 max  │     │
│  │  RAM: 2GB max  │      │  RAM: 2GB max  │     │
│  │  Auto-restart  │      │  Auto-restart  │     │
│  └────────────────┘      └────────────────┘     │
│           │                       │              │
│           └───────┬───────────────┘              │
│                   │                               │
│         ┌─────────▼─────────┐                    │
│         │  Volumes Persist. │                    │
│         │  - app/db         │                    │
│         │  - app/src        │                    │
│         │  - app/tmp        │                    │
│         └───────────────────┘                    │
└──────────────────────────────────────────────────┘
```

### Como Funciona

1. **Execução Infinita**: Cada worker roda indefinidamente com `restart: always`
2. **Reinicialização Automática**: Após `MAX_RUN_HOURS` horas, o container reinicia automaticamente
3. **Ambiente Limpo**: A cada reinicialização, o ambiente é limpo (exceto volumes persistentes)
4. **Sem Conflitos de Certificados**: Certificados digitais são limpos a cada restart
5. **Volumes Persistentes**: Apenas `app/db`, `app/src` e `app/tmp` persistem entre reinicializações

## 📊 Planejamento de Recursos

Para VPS da Hostinger (2 vCPU / 8GB RAM):

| Configuração | Workers | CPU/Worker | RAM/Worker | Uso Recomendado |
|--------------|---------|------------|------------|-----------------|
| **Recomendado** | 2 | 1.0 CPU | 2GB | RPAs pesadas balanceadas |
| Tarefas Leves | 3 | 0.5 CPU | 1.5GB | Automação leve |
| Tarefa Pesada | 1 | 2.0 CPU | 4GB | Uma RPA muito pesada |

## ⚙️ Comandos Úteis

### Gerenciamento de Workers

```bash
# Iniciar workers
docker compose -f docker-compose.worker.yml up -d

# Parar workers
docker compose -f docker-compose.worker.yml down

# Reiniciar workers
docker compose -f docker-compose.worker.yml restart

# Escalar para 3 workers
docker compose -f docker-compose.worker.yml up -d --scale rpa-worker=3

# Ver logs dos últimos 100 linhas
docker compose -f docker-compose.worker.yml logs --tail=100 -f

# Ver status e uso de recursos
docker stats
```

### Limpeza

```bash
# Parar e remover containers (mantém volumes)
docker compose -f docker-compose.worker.yml down

# Parar e remover tudo (incluindo volumes)
docker compose -f docker-compose.worker.yml down -v

# Limpar dados temporários manualmente
rm -rf app/tmp/*
```

## 📝 Escrevendo Scripts para Workers

Seu script RPA deve ser colocado em `app/src/` e seguir esta estrutura:

```python
#!/usr/bin/env python3
import time
import sys
from datetime import datetime

def main():
    """Função principal do worker"""
    print(f"[worker] Iniciando em {datetime.now()}")
    
    try:
        # Sua lógica RPA aqui
        while True:
            # Executar tarefa
            executar_tarefa_rpa()
            
            # Aguardar entre tarefas
            time.sleep(60)
    
    except Exception as e:
        print(f"[worker] Erro: {e}")
        return 1
    
    return 0

def executar_tarefa_rpa():
    """Sua automação RPA"""
    # Exemplo: Selenium, requisições HTTP, processamento de dados, etc.
    pass

if __name__ == '__main__':
    sys.exit(main())
```

Veja o exemplo completo em `app/src/worker_script.py`.

## 🔧 Configurações Avançadas

### Habilitar VNC para Debug

Para visualizar o que o worker está fazendo:

```bash
# Edite .env
USE_VNC=1
USE_XVFB=1
USE_OPENBOX=1

# Adicione porta no docker-compose.worker.yml
ports:
  - "5900:5900"

# Reinicie
docker compose -f docker-compose.worker.yml up -d

# Conecte com cliente VNC
vncviewer localhost:5900
```

### Baixar Script de URL Dinamicamente

**Importante:** SCRIPT_URL não é compatível com worker_wrapper.py. Você deve modificar o docker-compose.worker.yml:

1. Edite `docker-compose.worker.yml` e altere o comando:
```yaml
# Mude de:
command: python /app/worker_wrapper.py

# Para:
command: /app/entrypoint.sh
```

2. Configure a variável de ambiente SCRIPT_URL:
```bash
export SCRIPT_URL=https://exemplo.com/scripts/meu_rpa.py
```

3. Inicie os workers:
```bash
docker compose -f docker-compose.worker.yml up -d
```

**Nota:** Ao usar SCRIPT_URL, você perde o recurso de reinicialização automática baseada em tempo (MAX_RUN_HOURS). Você deve implementar a lógica de reinicialização no seu próprio script se necessário.

### Ajustar Limites de Recursos

Edite `docker-compose.worker.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: '1.5'      # Ajuste conforme necessário
      memory: 3072M    # Ajuste conforme necessário
```

## 🐛 Resolução de Problemas

### Workers reiniciando constantemente

Verifique os logs:
```bash
docker compose -f docker-compose.worker.yml logs --tail=50 rpa-worker
```

Problemas comuns:
- Script não encontrado: verifique se está em `app/src/`
- Erros de importação: verifique dependências no `requirements.txt`
- Erros de permissão: verifique permissões dos arquivos

### Alto uso de memória

- Reduza o número de workers
- Aumente `MAX_RUN_HOURS` para reiniciar menos frequentemente
- Verifique memory leaks no seu script
- Adicione limpeza explícita de memória no script

### Conflitos de certificados

Por isso os restarts limpos são importantes:
- Containers reiniciam a cada `MAX_RUN_HOURS` horas
- Cada reinício começa com ambiente limpo
- Apenas `app/db`, `app/src` e `app/tmp` persistem
- Armazenamento de certificados em `/app/.pki` é limpo no restart

## 📚 Documentação Completa

Para documentação completa em inglês, veja:
- [DOCKER_COMPOSE_WORKERS.md](DOCKER_COMPOSE_WORKERS.md) - Guia completo
- [README.md](README.md) - Documentação principal do projeto

## 💡 Dicas

1. **Teste Localmente**: Teste seus scripts localmente antes de colocar em produção
2. **Monitore Recursos**: Use `docker stats` para monitorar uso de CPU/RAM
3. **Logs Estruturados**: Use logging estruturado para facilitar troubleshooting
4. **Backup Regular**: Faça backup do diretório `app/db` regularmente
5. **Atualizações**: Rebuilde a imagem periodicamente para atualizações de segurança

## 🆘 Suporte

- GitHub Issues: https://github.com/nailtongomes/rpa-worker-selenium/issues
- Documentação: Veja README.md e DOCKER_COMPOSE_WORKERS.md

## 📄 Licença

Mesma licença do projeto principal.
