# Quick Reference: dockerfile.slim

## TL;DR
```bash
# Minimal build (recommended for production) - ~2-2.5 GB
docker build -f dockerfile.slim -t rpa:slim .

# Full debug build - ~3.5-4 GB
docker build -f dockerfile.slim \
  --build-arg ENABLE_VNC=1 \
  --build-arg ENABLE_NOVNC=1 \
  --build-arg ENABLE_FFMPEG=1 \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t rpa:debug .
```

## Build Arguments

| Argument | Default | What it does | Size +/- |
|----------|---------|--------------|----------|
| `ENABLE_VNC` | 0 | Installs x11vnc for VNC debugging | +100 MB |
| `ENABLE_FFMPEG` | 0 | Installs FFmpeg for screen recording | +300 MB |
| `ENABLE_NOVNC` | 0 | Installs noVNC for browser-based VNC | +50 MB |
| `ENABLE_PDF_TOOLS` | 0 | Installs ImageMagick + Ghostscript | +200 MB |
| `BUILD_PJEOFFICE` | 0 | Installs PJeOffice (Brazilian legal) | +200 MB |

## Runtime Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_XVFB` | 0 | Start virtual display |
| `USE_OPENBOX` | 0 | Start window manager |
| `USE_VNC` | 0 | Start VNC server (requires `ENABLE_VNC=1` at build) |
| `USE_NOVNC` | 0 | Start noVNC (requires `ENABLE_NOVNC=1` at build) |
| `USE_SCREEN_RECORDING` | 0 | Start screen recording (requires `ENABLE_FFMPEG=1` at build) |
| `USE_PJEOFFICE` | 0 | Start PJeOffice (requires `BUILD_PJEOFFICE=1` at build) |

## Common Use Cases

### 1. Production (Minimal)
```bash
# Build
docker build -f dockerfile.slim -t rpa:prod .

# Run
docker run --rm rpa:prod python /app/script.py
```

### 2. Development (VNC Debugging)
```bash
# Build
docker build -f dockerfile.slim --build-arg ENABLE_VNC=1 -t rpa:dev .

# Run
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa:dev python /app/script.py

# Connect: vncviewer localhost:5900
```

### 3. Browser-based Debugging (noVNC)
```bash
# Build
docker build -f dockerfile.slim \
  --build-arg ENABLE_VNC=1 \
  --build-arg ENABLE_NOVNC=1 \
  -t rpa:novnc .

# Run
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -p 6080:6080 \
  rpa:novnc python /app/script.py

# Open: http://localhost:6080/vnc.html
```

### 4. Screen Recording
```bash
# Build
docker build -f dockerfile.slim --build-arg ENABLE_FFMPEG=1 -t rpa:rec .

# Run
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_SCREEN_RECORDING=1 \
  -v $(pwd)/recordings:/app/recordings \
  rpa:rec python /app/script.py

# Video saved to: ./recordings/recording_*.mp4
```

### 5. Brazilian Legal (PJeOffice)
```bash
# Build
docker build -f dockerfile.slim --build-arg BUILD_PJEOFFICE=1 -t rpa:pje .

# Run
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  rpa:pje python /app/pje_script.py
```

## What's Included (Always)

✅ Chrome 142.0.7444.162 + ChromeDriver
✅ Firefox ESR + GeckoDriver
✅ Python 3.12 + Selenium + SeleniumBase
✅ Virtual display (Xvfb)
✅ Window manager (OpenBox)
✅ Certificate support (A1 .pfx/.p12)
✅ Screenshot capability
✅ Automation tools (wmctrl, xdotool, xautomation)
✅ OpenJDK 21 JRE (headless)

## What's Optional (Conditional)

🔧 VNC server (x11vnc) - `ENABLE_VNC=1`
🔧 FFmpeg - `ENABLE_FFMPEG=1`
🔧 noVNC + websockify - `ENABLE_NOVNC=1`
🔧 ImageMagick + Ghostscript - `ENABLE_PDF_TOOLS=1`
🔧 PJeOffice - `BUILD_PJEOFFICE=1`

## Size Comparison

| Build | Size | Use |
|-------|------|-----|
| Minimal | ~2-2.5 GB | Production |
| + VNC | ~2.6 GB | Basic debug |
| + noVNC | ~2.7 GB | Browser debug |
| + FFmpeg | ~2.8 GB | Recording |
| Full debug | ~3.5-4 GB | Development |
| Dockerfile.trixie | ~4 GB | All features always |

## Troubleshooting

**Build fails with SSL error?**
→ Network restrictions. Use `Dockerfile.alpine` or build in environment with internet access.

**VNC not working?**
→ Ensure `ENABLE_VNC=1` at **build time** and `-e USE_VNC=1` at runtime.

**noVNC not working?**
→ Requires both `ENABLE_VNC=1` and `ENABLE_NOVNC=1` at build time.

**Screen recording not working?**
→ Ensure `ENABLE_FFMPEG=1` at build time and `-e USE_SCREEN_RECORDING=1` at runtime.

**Image still too large?**
→ Use minimal build (no optional args) or consider `Dockerfile.alpine` for serverless.

## More Information

- [DOCKERFILE_SLIM.md](DOCKERFILE_SLIM.md) - Full documentation
- [DOCKERFILE_SLIM_EXAMPLES.md](DOCKERFILE_SLIM_EXAMPLES.md) - More examples
- [DOCKERFILE_SLIM_SUMMARY.md](DOCKERFILE_SLIM_SUMMARY.md) - Implementation details
- [DOCKERFILE_VERSIONS.md](DOCKERFILE_VERSIONS.md) - Compare all Dockerfiles

## Quick Decision

**Most users** → Use `dockerfile.slim` (minimal)
**Debugging needed** → Use `dockerfile.slim` with `ENABLE_VNC=1`
**Serverless** → Use `Dockerfile.alpine`
**Full features always** → Use `Dockerfile.trixie`

---

**Remember:** Build args control what's installed, runtime env vars control what's running.
