# VNC Remote Debugging - Quick Start Guide

This guide helps you quickly start using the VNC remote debugging feature to observe your automation in real-time.

## Prerequisites

- Docker installed on your machine
- For traditional VNC: A VNC client (vncviewer, RealVNC Viewer, TightVNC, etc.)
- For browser-based VNC: Any modern web browser (Chrome, Firefox, Edge, Safari)
- The rpa-worker-selenium image built

## Quick Start

### 1. Build the Image (if not already built)

```bash
docker build -t rpa-worker-selenium .
```

### 2. Choose Your Access Method

#### Option A: Browser-Based VNC (noVNC - Recommended)

**Easiest option - no VNC client installation required!**

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -p 6080:6080 \
  rpa-worker-selenium example_novnc_debug.py
```

Then open your browser and navigate to:
```
http://localhost:6080/vnc.html
```

Click "Connect" to start viewing the automation.

#### Option B: Traditional VNC Client

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa-worker-selenium example_vnc_debug.py
```

Connect with your VNC client:

```bash
# Linux/Mac
vncviewer localhost:5900

# Windows - use your VNC client GUI
# Connect to: localhost:5900
```

#### Option C: Both (Hybrid Access)

Enable both traditional VNC and browser-based noVNC:

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -p 5900:5900 \
  -p 6080:6080 \
  rpa-worker-selenium example_vnc_debug.py
```

Now you can access via:
- Browser: `http://localhost:6080/vnc.html`
- VNC client: `localhost:5900`

## Common Use Cases

### Debug Your Own Script (Browser-Based)

```bash
# Mount your script and use noVNC
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -p 6080:6080 \
  -v $(pwd)/my_script.py:/app/src/my_script.py \
  rpa-worker-selenium /app/src/my_script.py
```

Then navigate to `http://localhost:6080/vnc.html` in your browser.

### Use Custom Ports

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -e VNC_PORT=5901 \
  -e NOVNC_PORT=6081 \
  -p 5901:5901 \
  -p 6081:6081 \
  rpa-worker-selenium example_novnc_debug.py
```

Access via browser at `http://localhost:6081/vnc.html`

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
  -e USE_NOVNC=1 \
  -p 6080:6080 \
  rpa-worker-selenium-pje my_script.py
```

Access via browser at `http://localhost:6080/vnc.html`

### Use Docker Compose

Create or use the included `docker-compose.yml`:

```yaml
services:
  rpa-worker-vnc:
    image: rpa-worker-selenium:latest
    ports:
      - "6080:6080"  # noVNC browser access
      - "5900:5900"  # Traditional VNC (optional)
    environment:
      - USE_XVFB=1
      - USE_VNC=1
      - USE_NOVNC=1
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

Access via browser at `http://localhost:6080/vnc.html`

## Troubleshooting

### Can't Connect to noVNC

1. Make sure the container is running
2. Check the port mapping: `-p 6080:6080`
3. Check firewall settings on your machine
4. Verify noVNC is enabled: `-e USE_NOVNC=1`
5. Verify VNC is enabled: `-e USE_VNC=1`
6. Verify Xvfb is enabled: `-e USE_XVFB=1`
7. Check container logs: `docker logs <container-id>`

### Can't Connect to Traditional VNC

1. Make sure the container is running
2. Check the port mapping: `-p 5900:5900`
3. Check firewall settings on your machine
4. Verify VNC is enabled: `-e USE_VNC=1`
5. Verify Xvfb is enabled: `-e USE_XVFB=1`

### Black Screen in VNC/noVNC

1. Check that Xvfb started successfully in container logs
2. Wait a few seconds - Xvfb needs time to initialize
3. Try running with OpenBox: `-e USE_OPENBOX=1`
4. Check the browser console for JavaScript errors (noVNC only)

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
| `USE_XVFB` | 0 | Enable virtual display (required for VNC and noVNC) |
| `USE_VNC` | 0 | Enable VNC server (required for noVNC) |
| `USE_NOVNC` | 0 | Enable browser-based VNC access |
| `VNC_PORT` | 5900 | VNC server port |
| `NOVNC_PORT` | 6080 | noVNC WebSocket port |
| `SCREEN_WIDTH` | 1366 | Virtual display width |
| `SCREEN_HEIGHT` | 768 | Virtual display height |
| `USE_OPENBOX` | 0 | Enable window manager (optional, helps with complex GUIs) |

## Testing the Feature

Run the included examples to verify VNC is working:

### Test with noVNC (Browser-Based)

```bash
# Run the noVNC example
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -p 6080:6080 \
  rpa-worker-selenium example_novnc_debug.py

# Open browser to: http://localhost:6080/vnc.html
# Click "Connect"
```

### Test with Traditional VNC Client

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

## Advantages of noVNC over Traditional VNC

### Browser-Based (noVNC)
✅ No client installation required  
✅ Works from any device with a browser  
✅ Easy to share with team members  
✅ Cross-platform (Windows, Mac, Linux, mobile)  
✅ Can be proxied through Caddy for HTTPS/auth  

### Traditional VNC Client
✅ Lower latency  
✅ Better performance for extended sessions  
✅ More keyboard shortcuts supported  
✅ Can work offline (local network)  

**Recommendation:** Use noVNC for quick debugging and sharing. Use traditional VNC for longer interactive sessions.

## Security Notes

- Both VNC and noVNC have **no password** by default (suitable for local development)
- For production or untrusted networks:
  - Use SSH tunneling to connect to VNC
  - Set up a reverse proxy with authentication (see [VNC_CADDY_PROXY.md](VNC_CADDY_PROXY.md))
  - Run the container in a private network
  - Do not expose VNC/noVNC ports to the internet

## Alpine Image Note

**Important:** The noVNC feature is **not available** in `Dockerfile.alpine`. This is intentional to keep the Alpine image lightweight for serverless deployments. If you need noVNC, use one of the other Dockerfiles:
- `Dockerfile` (main unified - Chrome/Brave)
- `Dockerfile.firefox`
- `Dockerfile.ubuntu` (Debian Trixie-based with enhanced GUI support)

## Additional Resources

- Main README: See full documentation in [README.md](README.md)
- Traditional VNC example: See [example_vnc_debug.py](example_vnc_debug.py)
- Browser-based VNC example: See [example_novnc_debug.py](example_novnc_debug.py)
- Production proxy setup: See [VNC_CADDY_PROXY.md](VNC_CADDY_PROXY.md)
- Tests: Run `python test_vnc.py` and `python test_vnc_integration.py`
