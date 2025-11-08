[![Smoke Test](https://github.com/nailtongomes/rpa-worker-selenium/actions/workflows/smoke-test.yml/badge.svg)](https://github.com/nailtongomes/rpa-worker-selenium/actions/workflows/smoke-test.yml)

# rpa-worker-selenium

A production-ready Docker image for running dynamic Python scripts with Selenium automation. This image uses a multi-stage build and comes pre-configured with Chrome, ChromeDriver, and comprehensive dependencies for web automation and RPA tasks.

> **Note**: This repository provides four Dockerfile versions:
> - `Dockerfile` (default) - Uses Chromium from Debian repos, easier to build
> - `Dockerfile.chrome` - Uses Google Chrome with matched ChromeDriver for production
> - `Dockerfile.brave` - Uses Brave browser for privacy-focused automation
> - `Dockerfile.firefox` - Uses Firefox browser with GeckoDriver for Mozilla automation
> 
> See [DOCKERFILE_VERSIONS.md](DOCKERFILE_VERSIONS.md) for details on which to use.

## Features

- 🐍 Python 3.11 on Debian Bookworm
- 🌐 Selenium WebDriver & SeleniumBase
- 🚀 Google Chrome (specific version: 142.0.7444.59)
- 📦 ChromeDriver (matched to Chrome version from Chrome for Testing)
- 🖥️ Optional Xvfb (virtual display), OpenBox window manager, and VNC support
- ⚖️ Optional PJeOffice support (for Brazilian legal system automations)
- 🔧 Pre-configured for RPA and automation tasks
- 📊 Comprehensive packages: requests, beautifulsoup4, pandas, openpyxl, PyAutoGUI, and more
- 🔒 Non-root user setup for security
- 🎯 Multi-stage build for optimized image size
- 💡 Lightweight by default - optional services disabled for minimal resource usage

## Quick Start

### Building the Docker Image

**Default (Chromium):**
```bash
git clone https://github.com/nailtongomes/rpa-worker-selenium.git
cd rpa-worker-selenium
docker build -t rpa-worker-selenium .
```

**With Google Chrome:**
```bash
docker build -f Dockerfile.chrome -t rpa-worker-selenium .
```

**With Brave Browser:**
```bash
docker build -f Dockerfile.brave -t rpa-worker-selenium-brave .
```

**With Firefox:**
```bash
docker build -f Dockerfile.firefox -t rpa-worker-selenium-firefox .
```

> **Note:** Building `Dockerfile.chrome`, `Dockerfile.brave`, and `Dockerfile.firefox` requires internet access to specific domains during build:
> - Chrome: `dl.google.com`, `storage.googleapis.com`
> - Brave: `brave-browser-apt-release.s3.brave.com`, `storage.googleapis.com`, `googlechromelabs.github.io`
> - Firefox: `ftp.mozilla.org`, `github.com`
> 
> If you're behind a corporate firewall or in a restricted network, use the default `Dockerfile` (Chromium) instead.

### Running the Example Script

```bash
docker run --rm rpa-worker-selenium example_script.py
```

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

```bash
docker run --rm -it --user root rpa-worker-selenium bash
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
```

**Note:** PJeOffice download requires access to `pje-office.pje.jus.br` during build.

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

### Default Behavior (Lightweight Mode)

By default, all optional services are disabled for lightweight, headless operation:
- `USE_XVFB=0` - No virtual display
- `USE_OPENBOX=0` - No window manager
- `USE_PJEOFFICE=0` - PJeOffice not started (even if installed)
- `USE_VNC=0` - No VNC server

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

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRIPT_URL` | - | URL of the main Python script to download and execute |
| `HELPER_URLS` | - | Comma-separated list of helper script URLs to download |
| `SCRIPTS_DIR` | /app/src | Directory to save helper scripts |
| `TARGET_URL` | https://example.com/ | URL for smoke test |
| `CACHE_DIR` | /data | Directory for smoke test outputs |
| `SCREEN_WIDTH` | 1366 | Virtual display width |
| `SCREEN_HEIGHT` | 768 | Virtual display height |
| `USE_XVFB` | 0 | Enable Xvfb virtual display (set to 1 to enable) |
| `USE_OPENBOX` | 0 | Enable OpenBox window manager (set to 1 to enable) |
| `USE_PJEOFFICE` | 0 | Enable PJeOffice (set to 1 to enable, requires BUILD_PJEOFFICE=1 at build time) |
| `USE_VNC` | 0 | Enable VNC server (set to 1 to enable) |
| `VNC_PORT` | 5900 | VNC server port |
| `DISPLAY` | :99 | X11 display number |

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

### Changing Chrome Version

Edit the `CHROME_VERSION` ARG in the Dockerfile:

```dockerfile
ARG CHROME_VERSION=142.0.7444.59  # Change to your desired version
```

### Using a Different Python Version

Edit the first line of the Dockerfile:

```dockerfile
FROM python:3.12-slim-bookworm  # or any other version
```

## Testing

The repository includes a test suite to validate the functionality:

```bash
# Run the test suite
python test_features.py
```

The test suite validates:
- Script downloader URL parsing and filename extraction
- Smoke test title extraction logic
- Environment variable handling

## Troubleshooting

### Chrome/ChromeDriver Version Mismatch

The Dockerfile uses a specific Chrome version matched with its corresponding ChromeDriver from Chrome for Testing. If you need a different version, update the `CHROME_VERSION` ARG and rebuild:

```bash
docker build --build-arg CHROME_VERSION=142.0.7444.59 -t rpa-worker-selenium .
```

### Memory Issues

If you encounter memory issues, increase Docker's memory limit or ensure these options are in your Chrome configuration:

```python
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--no-sandbox')
```

### Permission Issues

The container runs as a non-root user (`rpauser` with UID 1000). If you need root access:

```bash
docker run --rm -it --user root rpa-worker-selenium bash
```

### SSL Certificate Issues

If you encounter SSL certificate issues, the image includes proper CA certificates. You may need to update them:

```bash
docker run --rm --user root rpa-worker-selenium apt-get update && apt-get install -y ca-certificates
```

## Security Features

- ✅ Non-root user (`rpauser`) by default
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
