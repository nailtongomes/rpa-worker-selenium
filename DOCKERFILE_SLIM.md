# Dockerfile.slim - Optimized Debian Trixie Image

## Overview

`dockerfile.slim` is an optimized version of `Dockerfile.trixie` that significantly reduces image size while preserving all critical functionality for Selenium-based RPA automation. The image uses `debian:trixie-slim` as the base and introduces build-time flags to control optional debug and PDF-related features.

## Key Optimizations

### 1. **Reduced Base Image**
- Uses `debian:trixie-slim` instead of full `debian:trixie`
- Saves hundreds of MBs in the base layer

### 2. **Conditional Debug Features**
- VNC, FFmpeg, noVNC, and PDF tools are **optional** (disabled by default)
- Install only what you need via build arguments
- Default build excludes all debug/heavy features

### 3. **Removed Audio Stack**
- No `pulseaudio` or other audio-only packages
- Focus on headless/GUI-over-X11 only

### 4. **Minimal Font Set**
- Removed `fonts-noto` and `fonts-noto-color-emoji` (heavy font families)
- Kept only `fonts-liberation` and `fonts-dejavu-core` (sufficient for Brazilian sites)

### 5. **Build Tools Cleanup**
- `build-essential` and `python3-dev` are purged after pip install
- Significantly reduces final image size

### 6. **Cache Cleanup**
- All `apt-get` commands followed by `rm -rf /var/lib/apt/lists/*`
- Pip cache cleaned with `rm -rf /root/.cache/pip`

## What's Always Included (Default Build)

The default build (`docker build -f dockerfile.slim -t image .`) includes:

✅ **Browsers & Drivers:**
- Chrome for Testing (version 142.0.7444.162)
- Firefox ESR (latest)
- ChromeDriver (matched to Chrome version)
- GeckoDriver (v0.36.0)

✅ **Python Environment:**
- Python 3.12 (Debian Trixie default)
- Virtual environment (`/opt/venv`) for PEP 668 compliance
- All packages from `requirements.txt` (Selenium, SeleniumBase, etc.)

✅ **GUI/X11 Support:**
- Xvfb (virtual display)
- OpenBox (window manager for certificate dialogs)
- wmctrl, xdotool, xautomation (automation tools)

✅ **Certificate Handling:**
- NSS tools for A1 digital certificates
- Chrome policy directory for AutoSelectCertificateForUrls
- Runtime certificate management (import/export/remove)

✅ **Screenshots:**
- Full support for `driver.save_screenshot()` via Selenium
- No extra packages needed (uses browser capabilities)

✅ **Java Runtime:**
- OpenJDK 21 JRE (headless) for Java-based signers

## What's Optional (Controlled by Build Args)

### 1. VNC Server (`ENABLE_VNC`)
**Default:** `0` (disabled)

When enabled, installs:
- `x11vnc` (VNC server)

**Use case:** Remote debugging, visual inspection of automation

**Build command:**
```bash
docker build -f dockerfile.slim --build-arg ENABLE_VNC=1 -t image-with-vnc .
```

**Runtime usage:**
```bash
docker run --rm -e USE_VNC=1 -p 5900:5900 image-with-vnc script.py
```

---

### 2. FFmpeg (`ENABLE_FFMPEG`)
**Default:** `0` (disabled)

When enabled, installs:
- `ffmpeg` (screen recording)

**Use case:** Recording automation sessions for debugging

**Build command:**
```bash
docker build -f dockerfile.slim --build-arg ENABLE_FFMPEG=1 -t image-with-ffmpeg .
```

**Runtime usage:**
```bash
docker run --rm -e USE_XVFB=1 -e USE_SCREEN_RECORDING=1 image-with-ffmpeg script.py
```

---

### 3. noVNC (`ENABLE_NOVNC`)
**Default:** `0` (disabled)

When enabled, installs:
- `git` (temporary, removed after install)
- noVNC (browser-based VNC client)
- `websockify` (WebSocket proxy for VNC)

**Use case:** Browser-based remote access (no VNC client needed)

**Build command:**
```bash
docker build -f dockerfile.slim --build-arg ENABLE_NOVNC=1 --build-arg ENABLE_VNC=1 -t image-with-novnc .
```

**Note:** Requires `ENABLE_VNC=1` as well (noVNC requires VNC server)

**Runtime usage:**
```bash
docker run --rm -e USE_VNC=1 -e USE_NOVNC=1 -p 6080:6080 image-with-novnc script.py
# Access via browser: http://localhost:6080/vnc.html
```

---

### 4. PDF Tools (`ENABLE_PDF_TOOLS`)
**Default:** `0` (disabled)

When enabled, installs:
- `imagemagick` (image/PDF processing)
- `ghostscript` (PDF manipulation)

**Use case:** PDF signing workflows (when not delegated to external APIs)

**Build command:**
```bash
docker build -f dockerfile.slim --build-arg ENABLE_PDF_TOOLS=1 -t image-with-pdf .
```

---

### 5. PJeOffice (`BUILD_PJEOFFICE`)
**Default:** `0` (disabled)

When enabled, downloads and installs PJeOffice (Brazilian legal system digital signature tool)

**Build command:**
```bash
docker build -f dockerfile.slim --build-arg BUILD_PJEOFFICE=1 -t image-with-pje .
```

**Runtime usage:**
```bash
docker run --rm -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_PJEOFFICE=1 image-with-pje script.py
```

## Build Examples

### Minimal Build (Default)
```bash
# Smallest image - core functionality only
docker build -f dockerfile.slim -t rpa-worker-slim .
```

**Size:** Significantly smaller than Dockerfile.trixie (~2-2.5 GB vs ~4 GB)

**Includes:** Chrome, Firefox, Selenium, screenshots, certificates

**Excludes:** VNC, FFmpeg, noVNC, ImageMagick/Ghostscript

---

### Debug Build (All Features)
```bash
# Full-featured image with all debug tools
docker build -f dockerfile.slim \
  --build-arg ENABLE_VNC=1 \
  --build-arg ENABLE_FFMPEG=1 \
  --build-arg ENABLE_NOVNC=1 \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t rpa-worker-debug .
```

**Size:** Similar to Dockerfile.trixie (~3.5-4 GB)

**Includes:** Everything from minimal + VNC + FFmpeg + noVNC + PDF tools

---

### Production Build with PJeOffice
```bash
# Production image with PJeOffice support
docker build -f dockerfile.slim \
  --build-arg BUILD_PJEOFFICE=1 \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t rpa-worker-pje .
```

**Use case:** Brazilian legal system automations with digital signatures

---

### Serverless-Ready Build
```bash
# Minimal image for AWS Lambda / Cloud Run
docker build -f dockerfile.slim -t rpa-worker-serverless .
```

**Use case:** Serverless environments where image size matters

**Note:** For extreme minimalism, consider `Dockerfile.alpine` instead

## Runtime Environment Variables

The following environment variables control optional services at runtime:

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_XVFB` | `0` | Start Xvfb virtual display |
| `USE_OPENBOX` | `0` | Start OpenBox window manager |
| `USE_VNC` | `0` | Start VNC server (requires `ENABLE_VNC=1` at build) |
| `USE_NOVNC` | `0` | Start noVNC (requires `ENABLE_NOVNC=1` at build) |
| `USE_PJEOFFICE` | `0` | Start PJeOffice (requires `BUILD_PJEOFFICE=1` at build) |
| `USE_SCREEN_RECORDING` | `0` | Start screen recording (requires `ENABLE_FFMPEG=1` at build) |
| `VNC_PORT` | `5900` | VNC server port |
| `NOVNC_PORT` | `6080` | noVNC web port |
| `SCREEN_WIDTH` | `1366` | Virtual display width |
| `SCREEN_HEIGHT` | `768` | Virtual display height |

## Usage Examples

### 1. Basic Headless Automation
```bash
docker run --rm rpa-worker-slim python /app/example_script.py
```

### 2. With Virtual Display (for screenshots)
```bash
docker run --rm \
  -e USE_XVFB=1 \
  rpa-worker-slim python /app/script.py
```

### 3. With VNC Debugging
```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa-worker-debug python /app/script.py

# Connect with VNC client:
vncviewer localhost:5900
```

### 4. With noVNC (Browser-based)
```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -p 6080:6080 \
  rpa-worker-debug python /app/script.py

# Access via browser:
# http://localhost:6080/vnc.html
```

### 5. With Screen Recording
```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_SCREEN_RECORDING=1 \
  -v $(pwd)/recordings:/app/recordings \
  rpa-worker-debug python /app/script.py

# Recording saved to ./recordings/recording_*.mp4
```

### 6. PJeOffice Automation
```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  rpa-worker-pje python /app/pje_script.py
```

## Comparison: dockerfile.slim vs Dockerfile.trixie

| Feature | Dockerfile.trixie | dockerfile.slim (default) | dockerfile.slim (all features) |
|---------|-------------------|---------------------------|-------------------------------|
| Base Image | `debian:trixie` | `debian:trixie-slim` | `debian:trixie-slim` |
| Image Size | ~4 GB | ~2-2.5 GB | ~3.5-4 GB |
| Chrome | ✅ | ✅ | ✅ |
| Firefox ESR | ✅ | ✅ | ✅ |
| VNC | ✅ | ❌ | ✅ (via ENABLE_VNC=1) |
| FFmpeg | ✅ | ❌ | ✅ (via ENABLE_FFMPEG=1) |
| noVNC | ✅ | ❌ | ✅ (via ENABLE_NOVNC=1) |
| ImageMagick/Ghostscript | ✅ | ❌ | ✅ (via ENABLE_PDF_TOOLS=1) |
| Audio Stack | ✅ | ❌ | ❌ |
| Heavy Fonts | ✅ | ❌ | ❌ |
| Build Tools (runtime) | ✅ | ❌ | ❌ |
| Screenshots | ✅ | ✅ | ✅ |
| Certificates (A1) | ✅ | ✅ | ✅ |
| PJeOffice | Optional | Optional | Optional |

## When to Use dockerfile.slim

✅ **Use dockerfile.slim** if:
- You want a smaller image for production
- You don't need VNC/noVNC for debugging
- You don't need screen recording
- PDF signing is handled by external APIs
- You want to control which features are included

❌ **Use Dockerfile.trixie** if:
- You always need all debug features
- You prefer a single image with everything included
- Image size is not a concern

✅ **Use Dockerfile.alpine** if:
- You need the absolute smallest image for serverless
- You don't need PJeOffice or complex GUI interactions
- Headless-only automation is sufficient

## Technical Details

### Multi-stage Build
- **Stage 1 (builder):** Downloads Chrome, Firefox, ChromeDriver, GeckoDriver
- **Stage 2 (runtime):** Copies binaries from builder, installs dependencies

### PEP 668 Compliance
- Uses Python virtual environment (`/opt/venv`) to comply with PEP 668
- Debian Trixie enforces externally-managed Python packages

### Certificate Management
- NSS database directories created but remain empty
- Runtime Python code manages certificate lifecycle
- Supports A1 (.pfx/.p12) certificates
- Chrome AutoSelectCertificateForUrls policy support

### Browser Versions
- **Chrome:** 142.0.7444.162 (from Chrome for Testing)
- **Firefox:** Latest ESR (automatically fetched)
- **ChromeDriver:** Matched to Chrome version
- **GeckoDriver:** v0.36.0

### Health Check
The image includes a health check that verifies both browsers are available:
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD chrome --version && firefox --version || exit 1
```

## Troubleshooting

### Image still too large?
1. Use default build (no optional args) - should be ~2-2.5 GB
2. Consider `Dockerfile.alpine` for serverless (~1.5 GB)
3. Check what's consuming space: `docker history image-name`

### Screenshots not working?
- Screenshots work via Selenium API (`driver.save_screenshot()`)
- No special packages required
- Ensure Chrome/Firefox are properly installed

### VNC not working?
- Verify `ENABLE_VNC=1` was used during build
- Check runtime env: `-e USE_XVFB=1 -e USE_VNC=1`
- Port mapping: `-p 5900:5900`

### noVNC not working?
- Requires both `ENABLE_VNC=1` and `ENABLE_NOVNC=1` at build time
- Runtime: `-e USE_VNC=1 -e USE_NOVNC=1`
- Port mapping: `-p 6080:6080`

### Screen recording not working?
- Verify `ENABLE_FFMPEG=1` was used during build
- Runtime: `-e USE_XVFB=1 -e USE_SCREEN_RECORDING=1`
- Mount recordings volume: `-v $(pwd)/recordings:/app/recordings`

## Contributing

If you find ways to further reduce the image size without breaking functionality, please open a PR!

## License

Same as parent repository.
