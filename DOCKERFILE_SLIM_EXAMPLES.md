# dockerfile.slim - Build Examples

This document provides practical examples for building and using the optimized `dockerfile.slim` image.

## Table of Contents
1. [Minimal Builds](#minimal-builds)
2. [Debug Builds](#debug-builds)
3. [Production Builds](#production-builds)
4. [Advanced Configurations](#advanced-configurations)
5. [Size Comparisons](#size-comparisons)

---

## Minimal Builds

### 1. Basic Slim Build (Recommended Default)
**What you get:** Chrome, Firefox, Selenium, screenshots, certificates

**What you DON'T get:** VNC, FFmpeg, noVNC, PDF tools

```bash
# Build the minimal image
docker build -f dockerfile.slim -t rpa-worker:slim .

# Run a basic script
docker run --rm rpa-worker:slim python /app/example_script.py

# Run with virtual display for screenshots
docker run --rm \
  -e USE_XVFB=1 \
  rpa-worker:slim python /app/script.py
```

**Expected size:** ~2-2.5 GB (vs ~4 GB for Dockerfile.trixie)

---

## Debug Builds

### 2. Build with VNC (Remote Debugging)
**Use case:** Visual inspection of automation, debugging failed scripts

```bash
# Build with VNC support
docker build -f dockerfile.slim \
  --build-arg ENABLE_VNC=1 \
  -t rpa-worker:vnc .

# Run with VNC enabled
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa-worker:vnc python /app/script.py

# Connect with VNC client
vncviewer localhost:5900
```

### 3. Build with noVNC (Browser-based VNC)
**Use case:** Remote debugging without VNC client, team collaboration

```bash
# Build with noVNC and VNC (noVNC requires VNC)
docker build -f dockerfile.slim \
  --build-arg ENABLE_VNC=1 \
  --build-arg ENABLE_NOVNC=1 \
  -t rpa-worker:novnc .

# Run with noVNC enabled
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -p 6080:6080 \
  rpa-worker:novnc python /app/script.py

# Access via browser
# http://localhost:6080/vnc.html
```

### 4. Build with Screen Recording
**Use case:** Recording automation sessions for review, compliance

```bash
# Build with FFmpeg for screen recording
docker build -f dockerfile.slim \
  --build-arg ENABLE_FFMPEG=1 \
  -t rpa-worker:recording .

# Run with screen recording
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_SCREEN_RECORDING=1 \
  -v $(pwd)/recordings:/app/recordings \
  rpa-worker:recording python /app/script.py

# Recording saved to ./recordings/recording_*.mp4
```

### 5. Full Debug Build (All Features)
**Use case:** Development, comprehensive debugging

```bash
# Build with all debug features
docker build -f dockerfile.slim \
  --build-arg ENABLE_VNC=1 \
  --build-arg ENABLE_NOVNC=1 \
  --build-arg ENABLE_FFMPEG=1 \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t rpa-worker:debug .

# Run with all debug features
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -e USE_SCREEN_RECORDING=1 \
  -p 5900:5900 \
  -p 6080:6080 \
  -v $(pwd)/recordings:/app/recordings \
  rpa-worker:debug python /app/script.py
```

**Expected size:** ~3.5-4 GB (similar to Dockerfile.trixie)

---

## Production Builds

### 6. Production Build with PJeOffice
**Use case:** Brazilian legal system automations with digital signatures

```bash
# Build with PJeOffice support
docker build -f dockerfile.slim \
  --build-arg BUILD_PJEOFFICE=1 \
  -t rpa-worker:pje .

# Run with PJeOffice
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  rpa-worker:pje python /app/pje_script.py
```

### 7. Production Build with PDF Tools
**Use case:** PDF signing workflows (when not using external APIs)

```bash
# Build with PDF manipulation tools
docker build -f dockerfile.slim \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t rpa-worker:pdf .

# Run PDF-related scripts
docker run --rm \
  -v $(pwd)/pdfs:/data \
  rpa-worker:pdf python /app/pdf_script.py
```

### 8. Production Build with PJeOffice + PDF Tools
**Use case:** Complete legal document automation

```bash
# Build with PJeOffice and PDF tools
docker build -f dockerfile.slim \
  --build-arg BUILD_PJEOFFICE=1 \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t rpa-worker:legal .

# Run legal automation
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  -v $(pwd)/documents:/data \
  rpa-worker:legal python /app/legal_automation.py
```

---

## Advanced Configurations

### 9. Multi-stage CI/CD Build
**Use case:** Build different variants for different environments

```bash
# Stage 1: Build minimal for production
docker build -f dockerfile.slim \
  -t myapp:prod .

# Stage 2: Build debug for staging
docker build -f dockerfile.slim \
  --build-arg ENABLE_VNC=1 \
  --build-arg ENABLE_NOVNC=1 \
  -t myapp:staging .

# Stage 3: Build full for development
docker build -f dockerfile.slim \
  --build-arg ENABLE_VNC=1 \
  --build-arg ENABLE_NOVNC=1 \
  --build-arg ENABLE_FFMPEG=1 \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t myapp:dev .
```

### 10. AWS Lambda / Serverless
**Use case:** Minimal image for serverless environments

```bash
# For extreme minimalism in Lambda, use Dockerfile.alpine instead
# But if you need debian:trixie-slim base:

docker build -f dockerfile.slim \
  -t rpa-worker:serverless .

# Deploy to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
docker tag rpa-worker:serverless <account>.dkr.ecr.us-east-1.amazonaws.com/rpa-worker:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/rpa-worker:latest
```

### 11. With BuildKit Cache (Faster Rebuilds)
**Use case:** Development with frequent rebuilds

```bash
# Enable BuildKit for cache mounts
DOCKER_BUILDKIT=1 docker build -f dockerfile.slim \
  -t rpa-worker:slim .

# Subsequent builds will be much faster due to layer caching
```

### 12. Custom Chrome/Firefox Versions
**Use case:** Testing specific browser versions

```bash
# Override default Chrome version
docker build -f dockerfile.slim \
  --build-arg CHROME_VERSION=141.0.7384.0 \
  --build-arg GECKODRIVER_VERSION=0.35.0 \
  -t rpa-worker:custom-versions .
```

---

## Size Comparisons

### Image Size by Configuration

| Configuration | Build Args | Approx Size | Use Case |
|---------------|------------|-------------|----------|
| **Minimal** | None | **~2-2.5 GB** | Production, serverless |
| **+ VNC** | `ENABLE_VNC=1` | ~2.6 GB | Basic debugging |
| **+ noVNC** | `ENABLE_VNC=1`, `ENABLE_NOVNC=1` | ~2.7 GB | Browser-based debugging |
| **+ FFmpeg** | `ENABLE_FFMPEG=1` | ~2.8 GB | Screen recording |
| **+ PDF Tools** | `ENABLE_PDF_TOOLS=1` | ~2.7 GB | PDF workflows |
| **+ PJeOffice** | `BUILD_PJEOFFICE=1` | ~2.8 GB | Brazilian legal |
| **Full Debug** | All enabled | **~3.5-4 GB** | Development |

### Comparison with Other Dockerfiles

| Dockerfile | Base | Default Size | With All Features |
|------------|------|--------------|-------------------|
| `Dockerfile.trixie` | debian:trixie (full) | ~4 GB | ~4 GB |
| **`dockerfile.slim`** | debian:trixie-slim | **~2-2.5 GB** | ~3.5-4 GB |
| `Dockerfile.alpine` | alpine:latest | ~1.5 GB | N/A (no optional features) |

### Size Reduction Examples

```bash
# Check image sizes
docker images | grep rpa-worker

# Example output:
# rpa-worker   slim       abc123   2.3GB
# rpa-worker   trixie     def456   4.1GB
# rpa-worker   debug      ghi789   3.7GB

# Savings: ~1.8 GB (44% reduction) compared to Dockerfile.trixie
```

---

## Quick Reference: Build Arg Cheat Sheet

```bash
# Copy and customize this template:
docker build -f dockerfile.slim \
  --build-arg CHROME_VERSION=142.0.7444.162 \
  --build-arg GECKODRIVER_VERSION=0.36.0 \
  --build-arg BUILD_PJEOFFICE=0 \
  --build-arg ENABLE_VNC=0 \
  --build-arg ENABLE_FFMPEG=0 \
  --build-arg ENABLE_NOVNC=0 \
  --build-arg ENABLE_PDF_TOOLS=0 \
  -t my-custom-image .
```

### ARG Reference Table

| Argument | Default | Description | Install Time Impact |
|----------|---------|-------------|---------------------|
| `CHROME_VERSION` | 142.0.7444.162 | Chrome for Testing version | N/A |
| `GECKODRIVER_VERSION` | 0.36.0 | GeckoDriver version | N/A |
| `BUILD_PJEOFFICE` | 0 | Install PJeOffice | +200 MB, +30s |
| `ENABLE_VNC` | 0 | Install x11vnc | +100 MB, +10s |
| `ENABLE_FFMPEG` | 0 | Install FFmpeg | +300 MB, +20s |
| `ENABLE_NOVNC` | 0 | Install noVNC + websockify | +50 MB, +15s |
| `ENABLE_PDF_TOOLS` | 0 | Install ImageMagick + Ghostscript | +200 MB, +15s |

---

## Environment Variables at Runtime

Set these when running the container:

```bash
docker run --rm \
  -e USE_XVFB=1 \           # Start virtual display
  -e USE_OPENBOX=1 \         # Start window manager
  -e USE_VNC=1 \             # Start VNC server (requires ENABLE_VNC=1 at build)
  -e USE_NOVNC=1 \           # Start noVNC (requires ENABLE_NOVNC=1 at build)
  -e USE_PJEOFFICE=1 \       # Start PJeOffice (requires BUILD_PJEOFFICE=1 at build)
  -e USE_SCREEN_RECORDING=1 \# Start recording (requires ENABLE_FFMPEG=1 at build)
  -e VNC_PORT=5900 \         # VNC port
  -e NOVNC_PORT=6080 \       # noVNC port
  -e SCREEN_WIDTH=1366 \     # Display width
  -e SCREEN_HEIGHT=768 \     # Display height
  my-image python /app/script.py
```

---

## Troubleshooting

### Image too large?
- Use minimal build (no build args)
- Consider `Dockerfile.alpine` for serverless

### Missing VNC/noVNC?
- Verify `ENABLE_VNC=1` and/or `ENABLE_NOVNC=1` at **build time**
- Runtime env vars alone won't work if not built with support

### Missing PDF tools?
- Verify `ENABLE_PDF_TOOLS=1` at **build time**
- Or delegate PDF signing to external APIs

### Build time too long?
- Use `DOCKER_BUILDKIT=1` for cache
- Remove unused features (don't set their ARGs)

---

## Best Practices

1. **Production:** Use minimal build, no optional features
2. **Staging:** Add VNC/noVNC for debugging
3. **Development:** Use full debug build
4. **CI/CD:** Build multiple variants in parallel
5. **Serverless:** Use minimal or `Dockerfile.alpine`

---

## Next Steps

- Read [DOCKERFILE_SLIM.md](DOCKERFILE_SLIM.md) for detailed documentation
- See [DOCKERFILE_VERSIONS.md](DOCKERFILE_VERSIONS.md) for comparison with other Dockerfiles
- Check [README.md](README.md) for general usage

---

**Note:** All examples assume you're in the repository root directory. Adjust paths as needed.
