# Dockerfile Versions

This repository provides three Dockerfile versions:

## 1. Dockerfile (Default - Chromium from Debian repos)

**Recommended for: Testing, restricted networks, simple use cases**

- Uses Chromium from Debian repositories
- No external downloads required during build
- Easier to build in restricted environments
- Slightly older Chrome version
- Fully functional for most automation tasks

**Build command:**
```bash
docker build -t rpa-worker-selenium .
```

## 2. Dockerfile.chrome (Production - Google Chrome with matched ChromeDriver)

**Recommended for: Production use, latest Chrome features, maximum compatibility**

- Uses multi-stage build for optimization
- Downloads specific Chrome version (142.0.7444.59)
- Downloads matched ChromeDriver from Chrome for Testing
- Latest Chrome features and updates
- Requires internet access to dl.google.com and storage.googleapis.com during build

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
- Requires internet access to brave-browser-apt-release.s3.brave.com during build

**Build command:**
```bash
docker build -f Dockerfile.brave -t rpa-worker-selenium-brave .
```

**Example usage:**
```bash
docker run --rm rpa-worker-selenium-brave example_script_brave.py
```

## Which Should You Use?

- **Use `Dockerfile`** if:
  - You're just getting started
  - You're behind a corporate firewall
  - You don't need the absolute latest Chrome version
  - You want faster, simpler builds

- **Use `Dockerfile.chrome`** if:
  - You're deploying to production
  - You need a specific Chrome version
  - You need maximum compatibility
  - You have unrestricted internet access during builds

- **Use `Dockerfile.brave`** if:
  - You need privacy-focused browsing automation
  - You want built-in ad-blocking capabilities
  - You're testing websites with Brave browser specifically
  - You prefer Brave's Chromium-based features

All versions include all the same Python packages and provide the same functionality for Selenium automation.
