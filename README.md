[![Smoke Test](https://github.com/nailtongomes/rpa-worker-selenium/actions/workflows/smoke-test.yml/badge.svg)](https://github.com/nailtongomes/rpa-worker-selenium/actions/workflows/smoke-test.yml)

# rpa-worker-selenium

A production-ready Docker image for running dynamic Python scripts with Selenium automation. This image uses optimized builds with cache mounts and comes pre-configured with Chrome, ChromeDriver, and comprehensive dependencies for web automation and RPA tasks.

> **Note**: This repository provides four Dockerfile versions:
> - `Dockerfile` (unified) - **NEW** Multi-browser support with build arg (Chrome or Brave)
> - `Dockerfile.firefox` - Uses Firefox browser with GeckoDriver for Mozilla automation
> - `Dockerfile.ubuntu` - **ENHANCED** Ubuntu-based with Chrome + Firefox + comprehensive GUI/window management
> - `Dockerfile.alpine` - Lightweight for serverless (Lambda, Cloud Run) - Chromium & Firefox ESR
> 
> See [DOCKERFILE_VERSIONS.md](DOCKERFILE_VERSIONS.md) for details on which to use.

## Features

- 🐍 Python 3.11 on Debian Bookworm
- 🌐 Selenium WebDriver & SeleniumBase
- 🚀 **NEW**: Unified Dockerfile with multi-browser support (Chrome, Brave)
- 📦 ChromeDriver (automatically matched to stable Chrome version)
- 🦊 **NEW**: Firefox support in Ubuntu image
- 🔐 Certificate support for .pfx files (CA/A1 tokens) with initialized NSS database
- 🔒 **NEW**: Runtime CA certificate management (install, list, remove)
- 🖥️ Optional Xvfb (virtual display), OpenBox window manager, and VNC support
- 🎥 Optional screen recording with FFmpeg for debugging
- ⚖️ Optional PJeOffice support (for Brazilian legal system automations)
- 🔧 Pre-configured for RPA and automation tasks
- 📊 Comprehensive packages: requests, beautifulsoup4, pandas, openpyxl, PyAutoGUI, and more
- 🔒 Runs as root by default for maximum compatibility (non-root user available if needed)
- 🎯 Multi-stage builds for optimized image size
- ⚡ Build cache optimizations with BuildKit for faster rebuilds
- 💡 Lightweight by default - optional services disabled for minimal resource usage
- ☁️ Serverless-optimized Alpine variant for Lambda, Cloud Run, and Fargate

## Quick Start

### Building the Docker Image

**Default (Chrome):**
```bash
git clone https://github.com/nailtongomes/rpa-worker-selenium.git
cd rpa-worker-selenium
DOCKER_BUILDKIT=1 docker build -t rpa-worker-selenium .
```

**With Brave Browser:**
```bash
DOCKER_BUILDKIT=1 docker build --build-arg BROWSER_TYPE=brave -t rpa-worker-selenium-brave .
```

**With Firefox:**
```bash
DOCKER_BUILDKIT=1 docker build -f Dockerfile.firefox -t rpa-worker-selenium-firefox .
```

**With Ubuntu (Enhanced GUI support + Chrome + Firefox):**
```bash
DOCKER_BUILDKIT=1 docker build -f Dockerfile.ubuntu -t rpa-worker-selenium-ubuntu .
```

**Alpine (Lightweight for Serverless) ⭐:**
```bash
DOCKER_BUILDKIT=1 docker build -f Dockerfile.alpine -t rpa-worker-selenium-alpine .
```

> **Note:** `DOCKER_BUILDKIT=1` enables build cache optimizations for faster rebuilds.

> **Note:** Building requires internet access to specific domains during build:
> - Chrome: `dl.google.com`, `storage.googleapis.com`, `googlechromelabs.github.io`
> - Brave: `brave-browser-apt-release.s3.brave.com`, `storage.googleapis.com`, `googlechromelabs.github.io`
> - Firefox: `ftp.mozilla.org`, `github.com`
> - Ubuntu: `dl.google.com`, `storage.googleapis.com`, `ftp.mozilla.org`, `github.com`
> 
> If you're behind a corporate firewall or in a restricted network, use `Dockerfile.alpine`.

### Running the Example Script

```bash
docker run --rm rpa-worker-selenium example_script.py
```

### Running the VNC Debugging Example

Test the VNC remote debugging feature with the included example:

```bash
# Build the image
docker build -t rpa-worker-selenium .

# Run with VNC enabled
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa-worker-selenium example_vnc_debug.py

# In another terminal, connect with VNC client
vncviewer localhost:5900
```

This example demonstrates a browser automation that you can observe live via VNC. It's perfect for understanding how the remote debugging feature works.

### Running Your Own Scripts

#### Option 1: Mount a script from your local machine

```bash
docker run --rm -v $(pwd)/my_script.py:/app/src/my_script.py rpa-worker-selenium /app/src/my_script.py
```

#### Option 2: Build the script into the image

1. Place your script in the repository directory
2. Rebuild the image
3. Run the container with your script:

```bash
docker run --rm rpa-worker-selenium your_script.py
```

#### Option 3: Use docker-compose

```bash
# Edit docker-compose.yml to specify your script
docker-compose up
```

## Writing Selenium Scripts

Here's a minimal example of a Selenium script:

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Configure Chrome options
chrome_options = Options()
chrome_options.add_argument('--headless=new')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

# Create service with explicit chromedriver path
service = Service('/usr/local/bin/chromedriver')

# Create driver
driver = webdriver.Chrome(service=service, options=chrome_options)

# Your automation code
driver.get("https://example.com")
print(driver.title)

# Clean up
driver.quit()
```

## Advanced Usage

### Using Brave Browser

When using the Brave browser Dockerfile, you need to specify the Brave binary location:

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Configure options for Brave
chrome_options = Options()
chrome_options.binary_location = "/usr/bin/brave-browser"
chrome_options.add_argument('--headless=new')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

# Create service
service = Service('/usr/local/bin/chromedriver')

# Create driver
driver = webdriver.Chrome(service=service, options=chrome_options)
driver.get("https://example.com")
print(driver.title)
driver.quit()
```

You can also provide the `BRAVE_BROWSER_PATH` environment variable when starting the container (or running the smoke tests) so that scripts know where the Brave binary lives.

Or use the included example script:

```bash
docker run --rm rpa-worker-selenium-brave example_script_brave.py
```

### Using Firefox Browser

When using the Firefox browser Dockerfile, configure Selenium for Firefox:

```python
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

# Configure Firefox options
firefox_options = Options()
firefox_options.add_argument('--headless')
firefox_options.add_argument('--no-sandbox')
firefox_options.add_argument('--disable-dev-shm-usage')

# Create service with explicit geckodriver path
service = Service('/usr/local/bin/geckodriver')

# Create driver
driver = webdriver.Firefox(service=service, options=firefox_options)
driver.get("https://example.com")
print(driver.title)
driver.quit()
```

Or use the included example script:

```bash
docker run --rm rpa-worker-selenium-firefox example_script_firefox.py
```

### Using Ubuntu Version for PJeOffice and Enhanced GUI Support

The Ubuntu-based Dockerfile is specifically designed for handling complex GUI interactions, including PJeOffice certificate dialogs:

```bash
# Build with PJeOffice support
docker build -f Dockerfile.ubuntu --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-ubuntu-pje .

# Run with full GUI support
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  rpa-worker-selenium-ubuntu-pje my_script.py
```

This version includes:
- Full Ubuntu 24.04 LTS base (not Debian slim)
- Comprehensive desktop environment libraries
- Enhanced window management tools (wmctrl, xdotool, xautomation)
- D-Bus and PolicyKit for authentication dialogs
- AT-SPI accessibility support
- PulseAudio for multimedia dialogs
- Complete GTK2/GTK3 support
- Java 21 runtime for applets and signing

Use this version when:
- You need to handle PJeOffice certificate password dialogs
- Your code works on Ubuntu but has issues in slim containers
- You need maximum GUI compatibility for complex window interactions

### Using SeleniumBase

```python
from seleniumbase import Driver

# Create driver with undetected-chromedriver mode
driver = Driver(uc=True, headless=True)
driver.get("https://example.com")
print(driver.title)
driver.quit()
```

### Interactive Python Shell

```bash
docker run --rm -it rpa-worker-selenium
```

### Run with Environment Variables

```bash
docker run --rm \
  -e SCREEN_WIDTH=1920 \
  -e SCREEN_HEIGHT=1080 \
  -e USE_XVFB=1 \
  rpa-worker-selenium my_script.py
```

### Access Container Shell

```bash
docker run --rm -it --entrypoint bash rpa-worker-selenium
```

### Run as Root (if needed)

Since version updates, the container runs as root by default for compatibility. The `rpauser` is still created for backward compatibility but not used by default.

```bash
docker run --rm -it rpa-worker-selenium bash
```

## Optional Services (PJeOffice, Xvfb, OpenBox)

The image supports optional services that can be enabled at build time (PJeOffice) or runtime (Xvfb, OpenBox).

### Building with PJeOffice Support

To include PJeOffice (required for some Brazilian legal system automations), use the `BUILD_PJEOFFICE` build argument:

```bash
# Default Dockerfile
docker build --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-pje .

# Chrome variant
docker build -f Dockerfile.chrome --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-pje .

# Firefox variant
docker build -f Dockerfile.firefox --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-pje .

# Brave variant
docker build -f Dockerfile.brave --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-pje .

# Ubuntu variant (recommended for PJeOffice certificate dialogs)
docker build -f Dockerfile.ubuntu --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-ubuntu-pje .
```

**Note:** PJeOffice download requires access to `pje-office.pje.jus.br` during build.

**Recommendation for PJeOffice:** If you're experiencing issues with certificate password dialogs, use the Ubuntu variant (`Dockerfile.ubuntu`). It includes comprehensive GUI libraries and window management tools specifically designed to handle these types of interactions.

### Running with Optional Services

Enable services at runtime using environment variables:

#### With Xvfb (Virtual Display)

```bash
docker run --rm \
  -e USE_XVFB=1 \
  rpa-worker-selenium my_script.py
```

#### With OpenBox Window Manager

OpenBox requires Xvfb to be enabled:

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  rpa-worker-selenium my_script.py
```

#### With PJeOffice

PJeOffice must be installed at build time (BUILD_PJEOFFICE=1):

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  rpa-worker-selenium-pje my_script.py
```

##### Using Custom PJeOffice Paths

If PJeOffice is installed in a non-standard location, you can specify custom paths:

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  -e PJEOFFICE_EXECUTABLE=/custom/path/pjeoffice-pro.sh \
  -e PJEOFFICE_CONFIG_DIR=/custom/config/dir \
  -e PJEOFFICE_CONFIG_FILE=/custom/config/dir/pjeoffice-pro.config \
  rpa-worker-selenium-pje my_script.py
```

The PJeOffice path environment variables allow you to:
- Edit the configuration file at runtime using the `PJEOFFICE_CONFIG_FILE` path
- Execute PJeOffice from a custom location using the `PJEOFFICE_EXECUTABLE` path
- Store configuration in a custom directory using the `PJEOFFICE_CONFIG_DIR` path

#### All Services Combined

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  -e SCREEN_WIDTH=1920 \
  -e SCREEN_HEIGHT=1080 \
  rpa-worker-selenium-pje my_script.py
```

### Remote Debugging with VNC

The image supports VNC (Virtual Network Computing) for remote debugging, allowing you to connect to the container and visually observe the automation in real-time. This is particularly useful when video recording is not working as expected or when you need to see what's happening during execution.

#### Enable VNC Server

VNC requires Xvfb to be enabled. The VNC server allows read-only viewing - you can see the automation but cannot interact with it:

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -p 5900:5900 \
  rpa-worker-selenium my_script.py
```

Then connect with any VNC client to `localhost:5900`:

```bash
# Using vncviewer (Linux/Mac)
vncviewer localhost:5900

# Using RealVNC Viewer (Windows/Mac/Linux)
# Connect to: localhost:5900

# Using TightVNC (Windows)
# Connect to: localhost:5900
```

#### Browser-Based VNC with noVNC (New!)

For easier access without installing a VNC client, you can use the built-in noVNC support to access VNC directly from your web browser:

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

Click "Connect" to view the automation in real-time. No VNC client installation required!

**Example with Firefox:**
```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -p 6080:6080 \
  rpa-worker-selenium-firefox example_script_firefox.py
```

**Note:** The noVNC feature is available in all Dockerfiles except `Dockerfile.alpine`.

#### VNC with Custom Ports

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_VNC=1 \
  -e USE_NOVNC=1 \
  -e VNC_PORT=5901 \
  -e NOVNC_PORT=6081 \
  -p 5901:5901 \
  -p 6081:6081 \
  rpa-worker-selenium my_script.py
```

#### VNC with PJeOffice and OpenBox

To debug PJeOffice interactions with visual feedback:

```bash
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

#### VNC with Docker Compose

Create a `docker-compose.yml` file:

```yaml
services:
  rpa-worker:
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
docker-compose up
```

Access via browser at `http://localhost:6080/vnc.html`

#### VNC Security Considerations

**Important:** The default VNC configuration uses no password (`-nopw` flag) for simplicity in local development. This is suitable for:
- Local development on your own machine
- Trusted internal networks
- Containers that are not exposed to the internet

For production or untrusted networks, consider:
- Using SSH tunneling to connect to VNC
- Setting up a reverse proxy with authentication (see [VNC_CADDY_PROXY.md](VNC_CADDY_PROXY.md))
- Running the container in a private network
- Using the noVNC browser interface behind a firewall

**Note:** Both VNC and noVNC require Xvfb to be running (`USE_XVFB=1`). If Xvfb is not enabled, they will be skipped with a warning message.

#### VNC with Reverse Proxy (Production)

For production deployments, use a reverse proxy with authentication and HTTPS. See the complete guide: **[VNC_CADDY_PROXY.md](VNC_CADDY_PROXY.md)**

Quick example with Caddy:

```bash
# Start with Caddy reverse proxy
docker-compose -f docker-compose.caddy.yml up -d

# Access via browser (noVNC)
open http://localhost:8080
```

The Caddy setup provides:
- Basic authentication
- HTTPS with automatic certificates (Let's Encrypt)
- Browser-based VNC client (noVNC)
- Centralized access control

### Screen Recording for Debugging

The image supports optional screen recording to help debug automation issues, especially when working with PJeOffice or visual interactions.

#### Enable Screen Recording

Screen recording requires Xvfb to be enabled:

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_SCREEN_RECORDING=1 \
  -v $(pwd)/recordings:/app/recordings \
  rpa-worker-selenium my_script.py
```

The recording will be saved as an MP4 file in `/app/recordings` with a timestamp in the filename (e.g., `recording_20241110_120345.mp4`).

#### Custom Recording Directory and Filename

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_SCREEN_RECORDING=1 \
  -e RECORDING_DIR=/data/recordings \
  -e RECORDING_FILENAME=my_automation.mp4 \
  -v $(pwd)/data:/data \
  rpa-worker-selenium my_script.py
```

#### Recording with PJeOffice

To debug PJeOffice interactions:

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  -e USE_SCREEN_RECORDING=1 \
  -v $(pwd)/recordings:/app/recordings \
  rpa-worker-selenium-pje my_script.py
```

**Recording Details:**
- Format: MP4 (H.264 codec)
- Frame rate: 15 fps (optimized for file size)
- Resolution: Matches `SCREEN_WIDTH` and `SCREEN_HEIGHT`
- The recording starts when the container starts and stops when the container exits

**Note:** Screen recording requires Xvfb to be running (`USE_XVFB=1`). If Xvfb is not enabled, recording will be skipped with a warning message.

### Default Behavior (Lightweight Mode)

By default, all optional services are disabled for lightweight, headless operation:
- `USE_XVFB=0` - No virtual display
- `USE_OPENBOX=0` - No window manager
- `USE_PJEOFFICE=0` - PJeOffice not started (even if installed)
- `USE_VNC=0` - No VNC server
- `USE_SCREEN_RECORDING=0` - No screen recording

This allows the container to run with minimal resources when these features are not needed.

## Running Scripts from URLs

The image supports downloading and executing scripts from URLs using environment variables:

### Download and Execute a Script

```bash
docker run --rm \
  -e SCRIPT_URL=https://example.com/my_script.py \
  rpa-worker-selenium
```

### Download Script with Helper Scripts

```bash
docker run --rm \
  -e SCRIPT_URL=https://example.com/main_script.py \
  -e HELPER_URLS=https://example.com/helper1.py,https://example.com/helper2.py \
  -v $(pwd)/data:/data \
  rpa-worker-selenium
```

Helper scripts are downloaded to `/app/src/` and can be imported by the main script.

### Run the Smoke Test

A smoke test is included to verify the setup:

```bash
# Using default URL ([https://example.com/](https://example.com/))
docker run --rm -v $(pwd)/data:/data rpa-worker-selenium python /app/smoke_test.py

# Using custom URL
docker run --rm \
  -e TARGET_URL=https://example.com \
  -v $(pwd)/data:/data \
  rpa-worker-selenium python /app/smoke_test.py
```

The smoke test tries SeleniumBase first and falls back to requests if unavailable.

#### Smoke Test with Process Checks

The smoke test can verify that Xvfb and PJeOffice processes are running:

```bash
# Build image with PJeOffice
docker build -f Dockerfile.chrome --build-arg BUILD_PJEOFFICE=1 -t rpa-worker-selenium-pje .

# Run smoke test with all services and process checks
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  -e CHECK_PROCESSES=1 \
  -e TARGET_URL=https://example.com \
  -v $(pwd)/data:/data \
  rpa-worker-selenium-pje \
  bash -c "sleep 5 && python /app/smoke_test.py"
```

The `CHECK_PROCESSES=1` flag enables verification that:
- Xvfb is running (when `USE_XVFB=1`)
- PJeOffice is running (when `USE_PJEOFFICE=1`)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRIPT_URL` | - | URL of the main Python script to download and execute |
| `HELPER_URLS` | - | Comma-separated list of helper script URLs to download |
| `SCRIPTS_DIR` | /app/src | Directory to save helper scripts |
| `TARGET_URL` | https://example.com/ | URL for smoke test |
| `CACHE_DIR` | /data | Directory for smoke test outputs |
| `TEST_HELPERS` | 0 | Test helper scripts functionality (set to 1 to enable) |
| `CHECK_PROCESSES` | 0 | Check if Xvfb and PJeOffice processes are alive (set to 1 to enable) |
| `SCREEN_WIDTH` | 1366 | Virtual display width |
| `SCREEN_HEIGHT` | 768 | Virtual display height |
| `USE_XVFB` | 0 | Enable Xvfb virtual display (set to 1 to enable) |
| `USE_OPENBOX` | 0 | Enable OpenBox window manager (set to 1 to enable) |
| `USE_PJEOFFICE` | 0 | Enable PJeOffice (set to 1 to enable, requires BUILD_PJEOFFICE=1 at build time) |
| `USE_VNC` | 0 | Enable VNC server (set to 1 to enable) |
| `USE_NOVNC` | 0 | Enable noVNC browser-based VNC (set to 1 to enable, requires USE_VNC=1) |
| `USE_SCREEN_RECORDING` | 0 | Enable screen recording (set to 1 to enable, requires USE_XVFB=1) |
| `VNC_PORT` | 5900 | VNC server port |
| `NOVNC_PORT` | 6080 | noVNC WebSocket port for browser access |
| `DISPLAY` | :99 | X11 display number |
| `RECORDING_DIR` | /app/recordings | Directory to save screen recordings |
| `RECORDING_FILENAME` | recording_YYYYMMDD_HHMMSS.mp4 | Filename for screen recording (auto-generated with timestamp if not specified) |
| `PJEOFFICE_CONFIG_DIR` | /app/.pjeoffice-pro | Directory for PJeOffice configuration files |
| `PJEOFFICE_CONFIG_FILE` | /app/.pjeoffice-pro/pjeoffice-pro.config | Full path to PJeOffice configuration file |
| `PJEOFFICE_EXECUTABLE` | /opt/pjeoffice/pjeoffice-pro.sh | Path to PJeOffice executable script |

## Installed Python Packages

### Core Automation
- selenium >= 4.25.0
- seleniumbase
- pyvirtualdisplay

### Web Scraping
- beautifulsoup4 == 4.13.3
- lxml == 5.3.0
- requests == 2.32.3

### Data Processing
- pandas == 2.2.3
- openpyxl == 3.1.5
- PyPDF2 == 3.0.1

### Image Processing & GUI Automation
- opencv-python == 4.10.0.84
- pillow >= 10.1.0
- PyAutoGUI
- pyperclip == 1.9.0

### Utilities
- filelock == 3.18.0
- psutil == 6.1.0
- pytz == 2024.2
- tinydb == 4.8.2
- PyJWT == 2.10.1
- pyotp == 2.9.0

## Architecture

This image uses a **multi-stage build**:

1. **Builder stage**: Downloads Chrome and ChromeDriver
2. **Runtime stage**: Installs system dependencies and Python packages

This approach minimizes the final image size while ensuring all necessary components are included.

## Customization

### Adding More Python Packages

Edit `requirements.txt` and rebuild the image:

```bash
echo "your-package==1.0.0" >> requirements.txt
docker build -t rpa-worker-selenium .
```

### Chrome Version

The Dockerfile automatically downloads the latest stable version of Google Chrome and its matching ChromeDriver. This ensures you always have the most recent stable release with security updates and bug fixes.

If you need a specific Chrome version instead:

1. Modify the builder stage to download a specific .deb version from Google's archive
2. Or switch back to Chrome for Testing by specifying a version:

```dockerfile
# In builder stage, replace the stable download with:
ARG CHROME_VERSION=142.0.7444.162
RUN curl -Lo "chrome-linux64.zip" "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip" \
 && unzip chrome-linux64.zip
# And adjust the runtime stage to extract and link accordingly
```

### Using a Different Python Version

Edit the first line of the Dockerfile:

```dockerfile
FROM python:3.12-slim-bookworm  # or any other version
```

## Testing

The repository includes multiple test suites to validate the functionality:

### Quick Test Suite

```bash
# Run the quick test suite
python test_features.py
```

The quick test suite validates:
- Script downloader URL parsing and filename extraction
- Smoke test title extraction logic
- Environment variable handling
- Brave browser example script structure

### Full Smoke Test

```bash
# Run the comprehensive smoke test
python full_smoke_test.py
```

The full smoke test performs extensive validation:
- Python version compatibility
- Core package imports (selenium, seleniumbase, requests, beautifulsoup4, pandas, etc.)
- Browser drivers availability (ChromeDriver, GeckoDriver)
- Selenium functionality with different browsers (Chrome, Firefox, Brave - optional)
- SeleniumBase functionality
- Requests library as fallback
- Script downloader functionality
- Helper scripts integration
- Environment variables configuration
- Process health checks (Xvfb, PJeOffice, screen recording - when enabled)
- Filesystem operations
- Network connectivity

#### Full Smoke Test Options

Environment variables for customizing the full smoke test:

| Variable | Default | Description |
|----------|---------|-------------|
| `TARGET_URL` | https://example.com | URL to test during browser validation |
| `CACHE_DIR` | /data | Directory to save test outputs and reports |
| `TEST_ALL_BROWSERS` | 0 | Test all available browsers (set to 1 to enable) |
| `BRAVE_BROWSER_PATH` | /usr/bin/brave-browser | Absolute path to the Brave browser binary (required for Brave tests) |
| `CHECK_PROCESSES` | 0 | Check if Xvfb and PJeOffice processes are alive (set to 1 to enable) |
| `VERBOSE` | 0 | Enable verbose output (set to 1 to enable) |

**Examples:**

```bash
# Run with custom URL and verbose output
TARGET_URL=https://example.com VERBOSE=1 python full_smoke_test.py

# Run with all browsers and process checks
TEST_ALL_BROWSERS=1 CHECK_PROCESSES=1 python full_smoke_test.py

# Run in Docker container with all features
docker run --rm \
  -e USE_XVFB=1 \
  -e CHECK_PROCESSES=1 \
  -e TARGET_URL=https://example.com \
  -e CACHE_DIR=/data \
  -v $(pwd)/data:/data \
  rpa-worker-selenium \
  python /app/full_smoke_test.py
```

The full smoke test generates detailed JSON reports with test results, timestamps, and success rates.

> **Note:** The Brave browser portion of the smoke test is only required for images built from `Dockerfile.brave`. Enable it by setting `TEST_ALL_BROWSERS=1` and pointing `BRAVE_BROWSER_PATH` to a valid Brave binary; other images will report the Brave test as skipped.

## Troubleshooting

### Chrome/ChromeDriver Version Mismatch

The Dockerfile automatically downloads the latest stable Chrome version and matching ChromeDriver, so version mismatches should not occur. Both are synchronized to use the same stable release version.

If you experience issues, rebuild the image to get the latest versions:

```bash
docker build -t rpa-worker-selenium .
```

For a specific version, see the "Chrome Version" section under Customization.

### Memory Issues

If you encounter memory issues, increase Docker's memory limit or ensure these options are in your Chrome configuration:

```python
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--no-sandbox')
```

### Permission Issues

The container runs as root by default for maximum compatibility. The non-root user `rpauser` (UID 1000) is still created for backward compatibility. If you need to run as the non-root user:

```bash
docker run --rm -it --user rpauser rpa-worker-selenium bash
```

### SSL Certificate Issues

If you encounter SSL certificate issues, the image includes proper CA certificates. You may need to update them:

```bash
docker run --rm rpa-worker-selenium apt-get update && apt-get install -y ca-certificates
```

### Runtime CA Certificate Management

All images include tools for managing CA certificates at runtime. This is essential for corporate environments with custom Certificate Authorities or systems requiring specific CA authentication.

#### Installing CA Certificates at Runtime

You can install custom CA certificates dynamically using the included tools:

```bash
# Using the example script
docker run --rm \
  -v /path/to/custom-ca.crt:/tmp/ca.crt:ro \
  rpa-worker-selenium \
  python /app/example_ca_runtime.py --install /tmp/ca.crt --name my-custom-ca

# Or manually
docker run --rm \
  -v /path/to/custom-ca.crt:/tmp/ca.crt:ro \
  rpa-worker-selenium \
  bash -c "
    cp /tmp/ca.crt /usr/local/share/ca-certificates/my-custom-ca.crt && \
    update-ca-certificates && \
    python your_script.py
  "
```

#### Listing CA Certificates

```bash
# List installed custom CA certificates
docker run --rm rpa-worker-selenium \
  python /app/example_ca_runtime.py --list

# List with detailed information
docker run --rm rpa-worker-selenium \
  python /app/example_ca_runtime.py --list --verbose
```

#### Removing CA Certificates

```bash
# Remove a CA certificate
docker run --rm rpa-worker-selenium \
  python /app/example_ca_runtime.py --remove my-custom-ca
```

For more details and Python API examples, see:
- **[CA Runtime Management Guide](CA_RUNTIME_MANAGEMENT.md)** - Complete CA certificate management documentation
- **[example_ca_runtime.py](example_ca_runtime.py)** - CA certificate management example script

### Client Certificate Authentication (.pfx/.p12 files)

The image includes support for client certificate authentication using .pfx (PKCS#12) files, commonly used for CA certificates or A1 digital tokens in Brazil. The NSS certificate database is pre-initialized for both the default app user and root user.

#### Using .pfx certificates with Chrome

To import a .pfx certificate into Chrome's certificate store:

```bash
# Import certificate into NSS database (run inside container)
pk12util -i /path/to/certificate.pfx -d sql:/app/.pki/nssdb

# Or for root user:
pk12util -i /path/to/certificate.pfx -d sql:/root/.pki/nssdb
```

You can also mount your certificate file when running the container:

```bash
docker run --rm \
  -v /path/to/your/certificate.pfx:/app/certs/certificate.pfx \
  rpa-worker-selenium \
  bash -c "pk12util -i /app/certs/certificate.pfx -d sql:/app/.pki/nssdb && python your_script.py"
```

#### Listing installed certificates

```bash
# List certificates in the database
certutil -L -d sql:/app/.pki/nssdb

# Or for root user:
certutil -L -d sql:/root/.pki/nssdb
```

**Note**: The NSS database password is empty by default for simplified automation. Chrome will automatically use certificates from the NSS database when accessing websites that require client authentication.

For personal certificate management (A1 tokens), see:
- **[A1 Certificate Guide](A1_CERTIFICATE_GUIDE.md)** - Complete A1 personal certificate documentation
- **[example_cert_management.py](example_cert_management.py)** - Personal certificate management example

## Security Features

- ✅ Root user by default for compatibility (non-root user `rpauser` available if needed)
- ✅ Minimal base image (slim-bookworm)
- ✅ Multi-stage build reduces attack surface
- ✅ No unnecessary packages in runtime image
- ✅ Proper file permissions and ownership

## License

MIT License - see LICENSE file for details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions, please open an issue on the GitHub repository.
