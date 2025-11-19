# Dockerfile Versions

This repository provides four Dockerfile versions with multi-browser support:

## 1. Dockerfile (Unified - Chrome or Brave)

**Recommended for: Production, PJeOffice compatibility, privacy-focused automation**

**NEW**: The unified Dockerfile now supports multiple browsers via build argument:
- **Chrome (default)**: Production-ready Google Chrome from Chrome for Testing
- **Brave**: Privacy-focused Brave browser with built-in ad-blocking

### Build with Chrome (default):
```bash
docker build -t rpa-worker-selenium .
# or explicitly
docker build --build-arg BROWSER_TYPE=chrome -t rpa-worker-selenium .
```

### Build with Brave:
```bash
docker build --build-arg BROWSER_TYPE=brave -t rpa-worker-selenium-brave .
```

**Features:**
- Multi-stage build for optimization
- Downloads specific Chrome version or installs Brave from official repository
- Downloads matched ChromeDriver from Chrome for Testing
- Optimized for PJeOffice digital signature compatibility (Chrome)
- Enhanced privacy features and built-in ad-blocking (Brave)
- Single Dockerfile for both browsers - reduces maintenance overhead

**Build Requirements:**
- Chrome: Requires internet access to `dl.google.com`, `storage.googleapis.com`, `googlechromelabs.github.io`
- Brave: Requires internet access to `brave-browser-apt-release.s3.brave.com`, `storage.googleapis.com`, `googlechromelabs.github.io`

## 2. Dockerfile.firefox (Firefox Browser)

**Recommended for: Firefox-specific testing, Gecko engine compatibility, Mozilla standards**

- Uses multi-stage build for optimization
- Downloads specific Firefox version (145.0)
- Downloads matched GeckoDriver (v0.36.0) from GitHub releases
- Mozilla's Gecko rendering engine
- Full support for Firefox WebDriver capabilities
- **Requires internet access to ftp.mozilla.org and github.com during build**

**Build command:**
```bash
docker build -f Dockerfile.firefox -t rpa-worker-selenium-firefox .
```

**Example usage:**
```bash
docker run --rm rpa-worker-selenium-firefox example_script_firefox.py
```

**Note:** If building behind a corporate firewall or in a restricted network environment, ensure that the following domains are accessible during build:
- `ftp.mozilla.org` (for Firefox download)
- `github.com` (for GeckoDriver download)

## 3. Dockerfile.trixie (Debian Trixie Desktop - Enhanced GUI/Window Management + Multi-Browser)

**Recommended for: PJeOffice certificate dialogs, complex window interactions, GUI automation, robust graphical worker with noVNC**

**ENHANCED**: Now uses Debian Trixie (13) - more complete and updated than Bookworm (12)!

- Uses Debian Trixie (13) as base image - latest testing version with up-to-date packages
- **NEW**: Includes both Chrome and Firefox browsers
- **NEW**: Includes both ChromeDriver and GeckoDriver
- Comprehensive desktop environment and GUI libraries
- Enhanced window management tools (wmctrl, xdotool, xautomation)
- Full GTK2/GTK3 support for certificate and authentication dialogs
- D-Bus and PolicyKit support for system dialogs
- AT-SPI accessibility for complex GUI interactions
- Audio support (PulseAudio) for multimedia dialogs
- noVNC support for browser-based remote access
- Robust for graphical environments with comprehensive package support
- Larger image size but maximum compatibility
- **Java 21 runtime for applets and PJeOffice/other Java-based signers**
- Health check to verify browser availability
- **Requires internet access to `storage.googleapis.com`, `ftp.mozilla.org`, `github.com` during build**

**Build command:**
```bash
docker build -f Dockerfile.trixie -t rpa-worker-selenium-debian .
```

**Build with PJeOffice support:**
```bash
docker build -f Dockerfile.trixie --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-debian-pje .
```

**Example usage with Chrome:**
```bash
# Basic usage
docker run --rm rpa-worker-selenium-debian example_script.py

# With GUI services enabled for PJeOffice
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  rpa-worker-selenium-debian-pje my_pjeoffice_script.py
```

**Example usage with Firefox:**
```bash
# Basic Firefox usage
docker run --rm rpa-worker-selenium-debian example_script_firefox.py

# With GUI services
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  rpa-worker-selenium-debian example_script_firefox.py
```

**Note:** This image is specifically designed to handle:
- PJeOffice certificate password dialogs and other Java-based digital signers
- Complex window interactions requiring full desktop environment
- GTK-based authentication prompts
- Robust graphical worker environments with noVNC support
- Applications requiring complete Debian Trixie environment compatibility
- Multi-browser testing (Chrome + Firefox) in same environment

- **Use `Dockerfile.trixie`** if:
  - You need to handle PJeOffice certificate password dialogs
  - You need support for Java-based digital signers and applets
  - You're experiencing window management issues with other images
  - You need maximum Debian Trixie environment compatibility
  - You want the latest testing packages (more updated than Bookworm)
  - You need full desktop environment support for complex GUI interactions
  - You're working with GTK-based authentication dialogs
  - You need noVNC for browser-based remote access
  - You need both Chrome and Firefox in the same image
  - Image size is less important than compatibility and feature completeness

## 4. Dockerfile.alpine (Lightweight Serverless - Chromium & Firefox)

**Recommended for: Serverless environments (AWS Lambda, Google Cloud Run), minimal footprint, cost optimization**

- Lightweight Debian-slim based image (named "alpine" for consistency)
- Minimal dependencies for reduced image size
- Includes Chromium browser and ChromeDriver from Debian repos
- Includes Firefox ESR browser
- NO PJeOffice, VNC, or GUI features (headless only)
- Optimized for serverless and containerized environments
- Perfect for Lambda functions, Cloud Run, Fargate, etc.
- Smaller image size than full-featured versions

**Build command:**
```bash
docker build -f Dockerfile.alpine -t rpa-worker-selenium-alpine .
```

**Example usage:**
```bash
# Basic headless automation
docker run --rm rpa-worker-selenium-alpine python /app/alpine_smoke_test.py

# Custom script
docker run --rm -v $(pwd)/data:/data rpa-worker-selenium-alpine python your_script.py
```

**Key Features:**
- **Browsers**: Chromium 142.x, Firefox 145.0
- **Drivers**: ChromeDriver (included), GeckoDriver (v0.36.0)
- **Size**: Significantly smaller than full images
- **Use Cases**: Lambda functions, Cloud Run, ECS Fargate, Kubernetes jobs
- **Limitations**: No GUI tools, no VNC, no PJeOffice support

**Testing:**
```bash
# Run the Alpine smoke test
docker run --rm -v $(pwd)/data:/data rpa-worker-selenium-alpine python /app/alpine_smoke_test.py
```

- **Use `Dockerfile.alpine`** if:
  - You're deploying to serverless environments (Lambda, Cloud Run, Fargate)
  - You need minimal image size for cost optimization
  - You only need headless browser automation
  - You don't need GUI features, VNC, or PJeOffice
  - You're running in containerized environments with resource constraints
  - You want faster container startup times

## Which Should You Use?

### Quick Decision Guide

| Dockerfile | Best For | Image Size | Browser(s) | GUI Support | Build Time |
|------------|----------|------------|------------|-------------|------------|
| `Dockerfile` (Chrome) | Production, PJeOffice | Medium | Chrome (Latest) | Yes | Medium |
| `Dockerfile` (Brave) | Privacy, Ad-blocking | Medium | Brave | Yes | Medium |
| `Dockerfile.firefox` | Firefox Testing | Medium | Firefox | Yes | Medium |
| `Dockerfile.trixie` | PJeOffice, Java Signers, noVNC | Large | **Chrome + Firefox** | **Full (Debian Trixie)** | Slow |
| `Dockerfile.alpine` | Serverless, Lambda | **Small** | Chromium & Firefox | No | Fast |

### Detailed Decision Guide

- **Use `Dockerfile` (Chrome)** if:
  - You're deploying to production
  - You need PJeOffice digital signature compatibility
  - You need the official Google Chrome browser
  - You need maximum compatibility
  - You have internet access during builds
  - This is the default and most common choice

- **Use `Dockerfile` (Brave)** if:
  - You need privacy-focused browsing automation
  - You want built-in ad-blocking capabilities
  - You're testing websites with Brave browser specifically
  - You prefer Brave's Chromium-based features
  - Same features as Chrome version but with Brave browser

- **Use `Dockerfile.firefox`** if:
  - You need to test with Firefox/Gecko engine specifically
  - You need Mozilla-specific WebDriver features
  - You're validating cross-browser compatibility
  - You prefer Firefox's rendering and standards compliance
  - You need Firefox-specific features or extensions

- **Use `Dockerfile.trixie`** if:
  - You need to handle PJeOffice certificate password dialogs
  - You need support for Java-based digital signers (PJeOffice and others)
  - You're experiencing window management issues with other images
  - You need Debian Trixie (13) - more updated packages than Bookworm (12)
  - You need robust graphical worker environment with noVNC support
  - You need full desktop environment support for complex GUI interactions
  - You're working with GTK-based authentication dialogs
  - **You need both Chrome AND Firefox in the same image**
  - Image size is less important than compatibility and feature completeness

- **Use `Dockerfile.alpine`** (⭐ Recommended for Serverless):
  - You're deploying to AWS Lambda, Google Cloud Run, Azure Container Instances
  - You need minimal image size for cost optimization (storage, bandwidth, cold starts)
  - You only need headless browser automation
  - You don't need GUI features, VNC, or PJeOffice
  - You're running in containerized environments with resource constraints
  - You want faster container startup times

## Build Cache Optimizations

All Dockerfiles now include build cache optimizations:

- **APT Cache Mounts**: `--mount=type=cache,target=/var/cache/apt` speeds up rebuilds by caching package downloads
- **Pip Cache Mounts**: `--mount=type=cache,target=/root/.cache/pip` speeds up Python package installations
- **Layer Separation**: Downloads and installations are separated into different layers for better caching
- **Multi-stage Builds**: Used where appropriate to keep final images small

To build with BuildKit (required for cache mounts):
```bash
DOCKER_BUILDKIT=1 docker build -f Dockerfile.chrome -t rpa-worker-selenium .
```

All versions include all the same Python packages and provide the same functionality for Selenium automation.
