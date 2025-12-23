# Docker Compose Workers for RPA Automation

This directory contains the configuration for running distributed RPA workers using Docker Compose.

## Overview

The worker setup provides:
- **Distributed execution**: Run multiple workers in parallel
- **Clean environments**: Each container restart starts fresh to avoid certificate conflicts
- **Automatic restart**: Workers restart automatically after max runtime hours
- **Resource limits**: Configurable CPU and memory limits per worker
- **Persistent storage**: Volumes for database, scripts, and temporary files

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Compose Host                      │
│                    (2 vCPU / 8GB RAM VM)                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │  RPA Worker #1   │         │  RPA Worker #2   │         │
│  │                  │         │                  │         │
│  │  CPU: 1.0 max    │         │  CPU: 1.0 max    │         │
│  │  RAM: 2GB max    │         │  RAM: 2GB max    │         │
│  │                  │         │                  │         │
│  │  Restart: Always │         │  Restart: Always │         │
│  └──────────────────┘         └──────────────────┘         │
│           │                            │                     │
│           └────────────┬───────────────┘                     │
│                        │                                     │
│              ┌─────────▼─────────┐                          │
│              │   Shared Volumes  │                          │
│              │                   │                          │
│              │  - app/db         │                          │
│              │  - app/src        │                          │
│              │  - app/tmp        │                          │
│              │  - app/logs       │                          │
│              └───────────────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose installed
- At least 2 vCPU and 8GB RAM (recommended for 2 workers)
- Git (to clone the repository)

### 2. Setup

```bash
# Clone the repository (if not already done)
git clone https://github.com/nailtongomes/rpa-worker-selenium.git
cd rpa-worker-selenium

# Create the required directories (if they don't exist)
mkdir -p app/src app/db app/tmp app/logs

# Place your RPA scripts in app/src/
# For example, copy your automation script:
cp my_automation.py app/src/
```

### 3. Configure Workers

Edit `docker-compose.worker.yml` or create a `.env` file:

```bash
# .env file example
SCRIPT_NAME=worker_script.py
MAX_RUN_HOURS=3
USE_XVFB=0
USE_OPENBOX=0
```

### 4. Start Workers

```bash
# Start 2 workers (recommended for 2vCPU/8GB RAM VM)
docker-compose -f docker-compose.worker.yml up -d --scale rpa-worker=2

# View logs
docker-compose -f docker-compose.worker.yml logs -f

# Check status
docker-compose -f docker-compose.worker.yml ps
```

### 5. Stop Workers

```bash
# Stop all workers
docker-compose -f docker-compose.worker.yml down

# Stop and remove volumes (clean start)
docker-compose -f docker-compose.worker.yml down -v
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRIPT_NAME` | `worker_script.py` | Name of the Python script to run (must be in `/app/src/`). Used with worker_wrapper.py. |
| `SCRIPT_URL` | - | Alternative: URL to download script from. **Note:** Requires changing command in docker-compose.worker.yml to use entrypoint directly. Not compatible with worker_wrapper.py. |
| `MAX_RUN_HOURS` | `3` | Maximum hours before forcing container restart (only with worker_wrapper.py) |
| `USE_XVFB` | `0` | Enable virtual display (0=disabled, 1=enabled) |
| `USE_OPENBOX` | `0` | Enable window manager (0=disabled, 1=enabled) |
| `USE_VNC` | `0` | Enable VNC for debugging (0=disabled, 1=enabled) |
| `SCREEN_WIDTH` | `1366` | Screen width for virtual display |
| `SCREEN_HEIGHT` | `768` | Screen height for virtual display |

### Resource Planning

For a typical Hostinger VPS with 2 vCPU and 8GB RAM:

| Configuration | Workers | CPU per Worker | RAM per Worker | Notes |
|--------------|---------|----------------|----------------|-------|
| **Recommended** | 2 | 1.0 CPU | 2GB | Balanced for heavy RPA tasks |
| Light Tasks | 3 | 0.5 CPU | 1.5GB | For lighter automation |
| Heavy Tasks | 1 | 2.0 CPU | 4GB | Single worker with full resources |

Adjust `docker-compose.worker.yml` resource limits based on your needs:

```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'      # Adjust based on number of workers
      memory: 2048M    # Adjust based on task requirements
```

### Scaling Workers

```bash
# Scale to 2 workers
docker-compose -f docker-compose.worker.yml up -d --scale rpa-worker=2

# Scale to 3 workers (for lighter tasks)
docker-compose -f docker-compose.worker.yml up -d --scale rpa-worker=3

# Scale to 1 worker (for heavy tasks)
docker-compose -f docker-compose.worker.yml up -d --scale rpa-worker=1
```

## Persistent Volumes

The following directories persist across container restarts:

- **`app/db/`**: Database files (SQLite, etc.)
- **`app/src/`**: Your Python scripts and modules
- **`app/tmp/`**: Temporary files that need to persist
- **`app/logs/`**: Log files for troubleshooting

Everything else is cleaned on each restart to avoid certificate conflicts.

## Writing Worker Scripts

Your worker scripts should:

1. Be placed in `app/src/` directory
2. Handle errors gracefully
3. Exit when done (container will restart automatically)
4. Optionally implement internal time checks

Example structure:

```python
#!/usr/bin/env python3
import time
import sys
from datetime import datetime

def main():
    print(f"[worker] Starting at {datetime.now()}")
    
    try:
        # Your RPA logic here
        while True:
            perform_task()
            time.sleep(60)  # Wait between tasks
    
    except Exception as e:
        print(f"[worker] Error: {e}")
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
```

See `app/src/worker_script.py` for a complete example.

## Monitoring

### View Logs

```bash
# All workers
docker-compose -f docker-compose.worker.yml logs -f

# Specific worker
docker-compose -f docker-compose.worker.yml logs -f rpa-worker

# Last 100 lines
docker-compose -f docker-compose.worker.yml logs --tail=100 -f
```

### Check Worker Status

```bash
# List running containers
docker-compose -f docker-compose.worker.yml ps

# Check resource usage
docker stats

# Check specific worker
docker inspect <container_id>
```

### Debug a Worker

Enable VNC for visual debugging:

```bash
# Edit docker-compose.worker.yml or set environment variables
USE_VNC=1
USE_XVFB=1
USE_OPENBOX=1

# Expose VNC port
# Add to docker-compose.worker.yml:
ports:
  - "5900:5900"

# Restart workers
docker-compose -f docker-compose.worker.yml up -d

# Connect with VNC client to localhost:5900
```

## Troubleshooting

### Worker keeps restarting

Check logs for errors:
```bash
docker-compose -f docker-compose.worker.yml logs --tail=50 rpa-worker
```

Common issues:
- Script not found: Ensure script is in `app/src/`
- Import errors: Check dependencies in `requirements.txt`
- Permission errors: Check file permissions in volumes

### High memory usage

- Reduce number of workers
- Increase `MAX_RUN_HOURS` to restart less frequently
- Check for memory leaks in your scripts
- Add explicit garbage collection in your scripts

### Certificate conflicts

This is why clean restarts are important:
- Containers restart every `MAX_RUN_HOURS` hours
- Each restart starts with a clean environment
- Only `app/db`, `app/src`, and `app/tmp` persist
- Certificate stores in `/app/.pki` are cleaned on restart

## Advanced Usage

### Using SCRIPT_URL

Download scripts dynamically from a URL:

**Important:** SCRIPT_URL is not compatible with worker_wrapper.py. You must modify the docker-compose.worker.yml:

1. Edit `docker-compose.worker.yml` and change the command:
```yaml
# Change from:
command: python /app/worker_wrapper.py

# To:
command: /app/entrypoint.sh
```

2. Set the SCRIPT_URL environment variable:
```bash
export SCRIPT_URL=https://example.com/scripts/my_automation.py
```

3. Start workers:
```bash
docker compose -f docker-compose.worker.yml up -d
```

**Note:** When using SCRIPT_URL, you lose the automatic time-based restart feature (MAX_RUN_HOURS). You must implement restart logic in your script if needed.

### Custom Build Args

Build with additional features:

```bash
# Edit docker-compose.worker.yml
build:
  args:
    ENABLE_VNC: 1        # Enable VNC
    ENABLE_NOVNC: 1      # Enable browser-based VNC
    ENABLE_FFMPEG: 1     # Enable screen recording
    BUILD_PJEOFFICE: 1   # Enable PJeOffice

# Rebuild
docker-compose -f docker-compose.worker.yml build
```

### Health Checks

Workers include health checks to ensure they're running:

```bash
# Check health status
docker inspect --format='{{.State.Health.Status}}' <container_id>

# View health check logs
docker inspect --format='{{json .State.Health}}' <container_id> | jq
```

## Best Practices

1. **Resource Planning**: Start with 2 workers and adjust based on monitoring
2. **Script Testing**: Test scripts locally before deploying to workers
3. **Error Handling**: Implement robust error handling in your scripts
4. **Logging**: Use structured logging for easier troubleshooting
5. **Monitoring**: Regularly check worker logs and resource usage
6. **Backups**: Regularly backup `app/db` directory
7. **Updates**: Periodically rebuild images to get security updates

## Support

For issues or questions:
- GitHub Issues: https://github.com/nailtongomes/rpa-worker-selenium/issues
- Documentation: See main README.md

## License

Same as the main project.
