# Simple RPA Worker with Docker Compose

Download and run RPA scripts from URL with automatic restart.

## Execution Modes

The worker supports three execution modes:

### 1. Single Execution Mode (Default)
Runs a script once from `SCRIPT_URL` and exits.

### 2. Loop Mode (`WORKER_LOOP=1`)
Continuously executes the script with automatic restart between iterations.

### 3. Standby Mode (`WORKER_MODE=standby`)
Runs an HTTP server that waits for task payloads via POST requests.
After executing each task, the container restarts to clear memory.

## Quick Start

### Single Execution or Loop Mode

1. **Create directories:**
```bash
mkdir -p app/src app/db app/tmp app/logs
```

2. **Set your script URL:**
```bash
# Create .env file
cp .env.example .env

# Edit .env and set SCRIPT_URL
nano .env
```

3. **Start the worker:**
```bash
docker compose -f docker-compose.worker.yml up -d
```

4. **View logs:**
```bash
docker compose -f docker-compose.worker.yml logs -f
```

## How It Works

1. Worker downloads your script from SCRIPT_URL
2. Script runs and does its work
3. When script exits (with error after ~1 hour), container restarts automatically
4. All data in `app/db`, `app/src`, `app/tmp`, and `app/logs` persists between restarts

## Your Script Requirements

Your Python script should:
- Run for your desired time (e.g., 1 hour)
- Raise an error or exit when done to trigger restart
- Save important data to `/app/db`, `/app/tmp`, or `/app/logs`

Example:
```python
import time
import sys

def main():
    start_time = time.time()
    max_runtime = 3600  # 1 hour in seconds
    
    while True:
        # Do your RPA work here
        do_work()
        
        # Check if 1 hour passed
        if time.time() - start_time >= max_runtime:
            print("Max runtime reached, exiting to restart")
            sys.exit(1)  # Exit with error to trigger restart
        
        time.sleep(60)  # Wait between tasks

if __name__ == "__main__":
    main()
```

## Persistent Data

The following directories persist between restarts:
- `app/db` - Database files
- `app/src` - Downloaded scripts (cached)
- `app/tmp` - Cache and temporary files
- `app/logs` - Log files

## Commands

```bash
# Start worker
docker compose -f docker-compose.worker.yml up -d

# Stop worker
docker compose -f docker-compose.worker.yml down

# View logs
docker compose -f docker-compose.worker.yml logs -f

# Restart worker
docker compose -f docker-compose.worker.yml restart

# Check status
docker compose -f docker-compose.worker.yml ps
```

## Troubleshooting

**Worker keeps restarting immediately:**
- Check logs: `docker compose -f docker-compose.worker.yml logs`
- Verify SCRIPT_URL is accessible
- Check your script for errors

**Script not found:**
- Verify SCRIPT_URL environment variable is set
- Check if URL is accessible from container

**Need to clear cache:**
```bash
# Stop worker and clear temp files
docker compose -f docker-compose.worker.yml down
rm -rf app/tmp/*
docker compose -f docker-compose.worker.yml up -d
```

## Standby Mode (HTTP Server)

Standby mode runs an HTTP server that waits for task requests instead of immediately executing a script.

### Starting Standby Mode

```bash
docker run -d \
  --name rpa-standby \
  -p 8080:8080 \
  -e WORKER_MODE=standby \
  -e TASK_SERVER_PORT=8080 \
  -e TASK_AUTH_TOKEN=your-secret-token \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  --restart=always \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest
```

### Sending Tasks

Send a POST request to `/task` with a JSON payload:

```bash
curl -X POST http://localhost:8080/task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{
    "script_url": "https://example.com/script.py",
    "script_name": "script.py",
    "payload": {
      "foo": "bar",
      "custom_data": "value"
    }
  }'
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "message": "Task accepted and execution started",
  "script_url": "https://example.com/script.py",
  "script_name": "script.py"
}
```

### Payload Fields

- `script_url` (required): HTTPS URL of the Python script to download
- `script_name` (required): Expected filename (must match URL filename)
- `payload` (optional): JSON object with custom data for your script

### Health Check

Check server status:

```bash
curl http://localhost:8080/health
```

**Response:**
```json
{
  "status": "healthy",
  "mode": "standby",
  "task_executing": false,
  "timestamp": "2024-01-15T10:30:45.123456"
}
```

### Environment Variables for Standby Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_MODE` | `pull` | Set to `standby` to enable HTTP server mode |
| `TASK_SERVER_PORT` | `8080` | Port for HTTP server to listen on |
| `TASK_AUTH_TOKEN` | `""` | Bearer token for authentication (optional but recommended) |
| `WORKER_TIMEOUT` | `3600` | Script execution timeout in seconds |

### Security

- Always use `TASK_AUTH_TOKEN` in production
- Only HTTPS URLs are accepted for `script_url`
- The server validates the `script_name` matches the URL filename

### Accessing Task Payload in Your Script

Your script can read the task payload from the JSON file:

```python
import os
import json

# Read task payload if available
payload_file = os.getenv("TASK_PAYLOAD_FILE")
if payload_file:
    with open(payload_file, 'r') as f:
        payload = json.load(f)
    print(f"Received payload: {payload}")
else:
    print("No payload provided")

def main():
    # Your automation logic here
    pass

if __name__ == "__main__":
    main()
```

### Container Restart Behavior

After executing a task:
1. Script completes (success or failure)
2. Container exits automatically
3. Docker/Kubernetes restarts the container (if restart policy is set)
4. Server starts fresh and ready for the next task

This ensures:
- Clean memory state between tasks
- No object accumulation from previous executions
- Consistent execution environment
