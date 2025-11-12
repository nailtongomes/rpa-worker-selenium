# VNC Remote Debugging - Quick Start Guide

This guide helps you quickly start using the VNC remote debugging feature to observe your automation in real-time.

## Prerequisites

- Docker installed on your machine
- A VNC client (vncviewer, RealVNC Viewer, TightVNC, etc.)
- The rpa-worker-selenium image built

## Quick Start

### 1. Build the Image (if not already built)

```bash
docker build -t rpa-worker-selenium .
```

### 2. Run with VNC Enabled

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa-worker-selenium example_vnc_debug.py
```

### 3. Connect with VNC Client

In another terminal or using your VNC client application:

```bash
# Linux/Mac
vncviewer localhost:5900

# Windows - use your VNC client GUI
# Connect to: localhost:5900
```

## Common Use Cases

### Debug Your Own Script

```bash
# Mount your script
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  -v $(pwd)/my_script.py:/app/src/my_script.py \
  rpa-worker-selenium /app/src/my_script.py
```

### Use Custom VNC Port

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e VNC_PORT=5901 \
  -p 5901:5901 \
  rpa-worker-selenium example_vnc_debug.py
```

### Debug with PJeOffice

```bash
# Build with PJeOffice support first
docker build --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-pje .

# Run with all services
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa-worker-selenium-pje my_script.py
```

### Use Docker Compose

Create or use the included `docker-compose.yml`:

```yaml
services:
  rpa-worker-vnc:
    image: rpa-worker-selenium:latest
    ports:
      - "5900:5900"
    environment:
      - USE_XVFB=1
      - USE_VNC=1
      - SCREEN_WIDTH=1920
      - SCREEN_HEIGHT=1080
    volumes:
      - ./scripts:/app/src
    command: python /app/src/my_script.py
```

Then run:

```bash
docker-compose up rpa-worker-vnc
# Or with the debug profile:
docker-compose --profile debug up
```

## Troubleshooting

### Can't Connect to VNC

1. Make sure the container is running
2. Check the port mapping: `-p 5900:5900`
3. Check firewall settings on your machine
4. Verify VNC is enabled: `-e USE_VNC=1`
5. Verify Xvfb is enabled: `-e USE_XVFB=1`

### Black Screen in VNC

1. Check that Xvfb started successfully in container logs
2. Wait a few seconds - Xvfb needs time to initialize
3. Try running with OpenBox: `-e USE_OPENBOX=1`

### Want to See Browser Window

Make sure your script does NOT use `--headless` mode:

```python
# ❌ This won't show in VNC
chrome_options.add_argument('--headless')

# ✅ This will show in VNC (remove headless)
# chrome_options.add_argument('--headless')  # Comment out or remove
```

### Custom Screen Resolution

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e SCREEN_WIDTH=1920 \
  -e SCREEN_HEIGHT=1080 \
  -p 5900:5900 \
  rpa-worker-selenium my_script.py
```

## Security Notes

- The default VNC configuration has **no password** (suitable for local development)
- For production or untrusted networks:
  - Use SSH tunneling to connect to VNC
  - Set up a reverse proxy with authentication
  - Run the container in a private network
  - Do not expose VNC port to the internet

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_XVFB` | 0 | Enable virtual display (required for VNC) |
| `USE_VNC` | 1 | Enable VNC server |
| `VNC_PORT` | 5900 | VNC server port |
| `SCREEN_WIDTH` | 1366 | Virtual display width |
| `SCREEN_HEIGHT` | 768 | Virtual display height |
| `USE_OPENBOX` | 0 | Enable window manager (optional, helps with complex GUIs) |

## Testing the Feature

Run the included example to verify VNC is working:

```bash
# Run the example
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa-worker-selenium example_vnc_debug.py

# In another terminal, connect
vncviewer localhost:5900
```

You should see:
1. Browser window opening
2. Navigation to example.com
3. Elements being highlighted
4. Navigation to python.org
5. Browser closing

## Additional Resources

- Main README: See full documentation in [README.md](README.md)
- Example script: See [example_vnc_debug.py](example_vnc_debug.py)
- Tests: Run `python test_vnc.py` and `python test_vnc_integration.py`
