# Dockerfile Versions

This repository provides six Dockerfile versions:

## 1. Dockerfile (Default - Google Chrome from Chrome for Testing)

**Recommended for: Production, PJeOffice compatibility, standard use cases**

- Uses Google Chrome from Chrome for Testing (official binaries)
- Multi-stage build for optimization
- Downloads specific Chrome version (142.0.7444.162)
- Downloads matched ChromeDriver from Chrome for Testing
- Optimized for PJeOffice digital signature compatibility
- Requires internet access to storage.googleapis.com during build

**Build command:**
```bash
docker build -t rpa-worker-selenium .
```

## 2. Dockerfile.chrome (Production - Google Chrome with matched ChromeDriver)

**Recommended for: Production use, latest Chrome features, maximum compatibility**

- Uses multi-stage build for optimization
- Downloads specific Chrome version (142.0.7444.162)
- Downloads matched ChromeDriver from Chrome for Testing
- Latest Chrome features and updates
- Identical to default Dockerfile (both use Google Chrome for Testing)
- Requires internet access to storage.googleapis.com during build

**Build command:**
```bash
docker build -f Dockerfile.chrome -t rpa-worker-selenium .
```

## 3. Dockerfile.brave (Brave Browser)

**Recommended for: Privacy-focused automation, ad-blocking, Brave-specific features**

- Uses Brave browser from official Brave repository
- Built on Chromium, fully compatible with Selenium/ChromeDriver
- Enhanced privacy features and built-in ad-blocking
- Latest stable Brave browser version
- **Requires internet access to brave-browser-apt-release.s3.brave.com and storage.googleapis.com during build**

**Build command:**
```bash
docker build -f Dockerfile.brave -t rpa-worker-selenium-brave .
```

**Example usage:**
```bash
docker run --rm rpa-worker-selenium-brave example_script_brave.py
```

**Note:** If building behind a corporate firewall or in a restricted network environment, ensure that the following domains are accessible during build:
- `brave-browser-apt-release.s3.brave.com` (for Brave browser installation)
- `storage.googleapis.com` (for ChromeDriver download)
- `googlechromelabs.github.io` (for ChromeDriver version lookup)

## 4. Dockerfile.firefox (Firefox Browser)

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

## 5. Dockerfile.ubuntu (Ubuntu Desktop - Enhanced GUI/Window Management)

**Recommended for: PJeOffice certificate dialogs, complex window interactions, GUI automation, maximum Ubuntu compatibility**

- Uses Ubuntu 22.04 LTS as base image (instead of Debian slim)
- Uses Google Chrome from Chrome for Testing (version 142.0.7444.162)
- Comprehensive desktop environment and GUI libraries
- Enhanced window management tools (wmctrl, xdotool, xautomation)
- Full GTK2/GTK3 support for certificate and authentication dialogs
- D-Bus and PolicyKit support for system dialogs
- AT-SPI accessibility for complex GUI interactions
- Audio support (PulseAudio) for multimedia dialogs
- More closely matches native Ubuntu development environment
- Larger image size but maximum compatibility
- **Requires internet access to storage.googleapis.com during build**

**Build command:**
```bash
docker build -f Dockerfile.ubuntu -t rpa-worker-selenium-ubuntu .
```

**Build with PJeOffice support:**
```bash
docker build -f Dockerfile.ubuntu --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-ubuntu-pje .
```

**Example usage:**
```bash
# Basic usage
docker run --rm rpa-worker-selenium-ubuntu example_script.py

# With GUI services enabled for PJeOffice
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  rpa-worker-selenium-ubuntu-pje my_pjeoffice_script.py
```

**Note:** This image is specifically designed to handle:
- PJeOffice certificate password dialogs
- Complex window interactions requiring full desktop environment
- GTK-based authentication prompts
- Applications requiring complete Ubuntu environment compatibility

- **Use `Dockerfile.ubuntu`** if:
  - You need to handle PJeOffice certificate password dialogs
  - You're experiencing window management issues with other images
  - You need maximum Ubuntu environment compatibility
  - Your Python code runs perfectly on Ubuntu but has issues in slim containers
  - You need full desktop environment support for complex GUI interactions
  - You're working with GTK-based authentication dialogs
  - Image size is less important than compatibility

## 6. Dockerfile.alpine (Lightweight Serverless - Chromium & Firefox)

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
| `Dockerfile` | Production, PJeOffice | Medium | Chrome (Latest) | Yes | Medium |
| `Dockerfile.chrome` | Production | Medium | Chrome (Latest) | Yes | Medium |
| `Dockerfile.firefox` | Firefox Testing | Medium | Firefox | Yes | Medium |
| `Dockerfile.brave` | Privacy, Ad-blocking | Medium | Brave | Yes | Medium |
| `Dockerfile.ubuntu` | PJeOffice, Complex GUI | Large | Chrome | Full | Slow |
| `Dockerfile.alpine` | Serverless, Lambda | **Small** | Chromium & Firefox | No | Fast |

### Detailed Decision Guide

- **Use `Dockerfile`** if:
  - You're deploying to production
  - You need PJeOffice digital signature compatibility
  - You need the official Google Chrome browser
  - You need maximum compatibility
  - You have internet access during builds

- **Use `Dockerfile.chrome`** if:
  - You're deploying to production
  - You need a specific Chrome version
  - You need maximum compatibility
  - You need PJeOffice digital signature compatibility
  - Same as default Dockerfile (both use Google Chrome for Testing)

- **Use `Dockerfile.brave`** if:
  - You need privacy-focused browsing automation
  - You want built-in ad-blocking capabilities
  - You're testing websites with Brave browser specifically
  - You prefer Brave's Chromium-based features

- **Use `Dockerfile.firefox`** if:
  - You need to test with Firefox/Gecko engine specifically
  - You need Mozilla-specific WebDriver features
  - You're validating cross-browser compatibility
  - You prefer Firefox's rendering and standards compliance

- **Use `Dockerfile.ubuntu`** if:
  - You need to handle PJeOffice certificate password dialogs
  - You're experiencing window management issues with other images
  - You need maximum Ubuntu environment compatibility
  - Your Python code runs perfectly on Ubuntu but has issues in slim containers
  - You need full desktop environment support for complex GUI interactions
  - You're working with GTK-based authentication dialogs
  - Image size is less important than compatibility

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
