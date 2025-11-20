# Browser Test Coverage

This document describes the comprehensive browser testing implemented in `test_browser_drivers.py`.

## Overview

The enhanced test suite provides **progressive testing** that covers three key scenarios for each browser:

1. **CLI Headless Tests**: Test the browser binary directly from the command line in headless mode
2. **WebDriver Headless Tests**: Test the browser via Selenium WebDriver in headless mode
3. **WebDriver Headful Tests**: Test the browser via Selenium WebDriver with a virtual display (Xvfb)

## Supported Browsers

### Chrome (Google Chrome)
- **CLI Test**: `google-chrome --headless=new --version`
- **Screenshot Test**: `google-chrome --headless=new --screenshot=...`
- **WebDriver Headless**: Selenium WebDriver with `--headless=new`
- **WebDriver Headful**: Selenium WebDriver with virtual display

### Brave Browser
- **CLI Test**: `brave-browser --headless=new --version`
- **Screenshot Test**: `brave-browser --headless=new --screenshot=...`
- **WebDriver Headless**: Selenium WebDriver with ChromeDriver and `--headless=new`
- **WebDriver Headful**: Selenium WebDriver with virtual display

### Firefox
- **CLI Test**: `firefox --headless --version`
- **Screenshot Test**: `firefox --headless --screenshot ...`
- **WebDriver Headless**: Selenium WebDriver with GeckoDriver and `--headless`
- **WebDriver Headful**: Selenium WebDriver with virtual display

## Test Flow

For each browser, the tests follow this progressive flow:

```
Stage 0: Check if browser binary and driver are available
  ↓ (skip all tests if not available)
Stage 1: CLI Headless Test
  ↓ (abort if CLI fails)
Stage 2: WebDriver Headless Test
  ↓ (continue regardless of result)
Stage 3: WebDriver Headful Test (only if DISPLAY is available)
```

## Test Results Format

Each test produces one of three results:
- **✓ PASS**: Test executed successfully
- **✗ FAIL**: Test executed but failed
- **⚠ SKIP**: Test was skipped (browser not available or no display)

Example output:
```
CHROME:
  cli_headless: ✓ PASS
  webdriver_headless: ✓ PASS
  webdriver_headful: ⚠ SKIP

FIREFOX:
  cli_headless: ✓ PASS
  webdriver_headless: ✓ PASS
  webdriver_headful: ✓ PASS

BRAVE:
  cli_headless: ⚠ SKIP
  webdriver_headless: ⚠ SKIP
  webdriver_headful: ⚠ SKIP
```

## Running Tests

### Basic Usage
```bash
python test_browser_drivers.py
```

### In Docker Containers

**Chrome (Headless only):**
```bash
docker run --rm rpa-worker-selenium python /app/test_browser_drivers.py
```

**Chrome (with virtual display for headful tests):**
```bash
docker run --rm -e USE_XVFB=1 rpa-worker-selenium python /app/test_browser_drivers.py
```

**Firefox:**
```bash
docker run --rm rpa-worker-selenium-firefox python /app/test_browser_drivers.py
```

**Brave:**
```bash
docker run --rm -e BROWSER_TYPE=brave rpa-worker-selenium python /app/test_browser_drivers.py
```

## Coverage by Dockerfile

### Dockerfile (Unified)
- **Chrome (BROWSER_TYPE=chrome)**
  - ✓ CLI Headless
  - ✓ WebDriver Headless
  - ✓ WebDriver Headful (with USE_XVFB=1)

- **Brave (BROWSER_TYPE=brave)**
  - ✓ CLI Headless
  - ✓ WebDriver Headless
  - ✓ WebDriver Headful (with USE_XVFB=1)

### Dockerfile.firefox
- ✓ Firefox CLI Headless
- ✓ Firefox WebDriver Headless
- ✓ Firefox WebDriver Headful (with USE_XVFB=1)

### Dockerfile.alpine
- ✓ Chromium CLI Headless
- ✓ Chromium WebDriver Headless
- ✓ Firefox CLI Headless
- ✓ Firefox WebDriver Headless
- ⚠ Headful tests skipped (lightweight, no GUI by default)

### Dockerfile.trixie
- ✓ Chrome CLI Headless
- ✓ Chrome WebDriver Headless
- ✓ Chrome WebDriver Headful (with USE_XVFB=1)
- ✓ Firefox ESR CLI Headless
- ✓ Firefox ESR WebDriver Headless
- ✓ Firefox ESR WebDriver Headful (with USE_XVFB=1)

## Benefits

1. **Comprehensive Coverage**: Tests all major execution modes (CLI, headless WebDriver, headful WebDriver)
2. **Clear Diagnostics**: Tests show exactly what works and what doesn't in each scenario
3. **Progressive Testing**: Early failures prevent wasting time on dependent tests
4. **Flexible**: Works both inside and outside Docker containers
5. **CI-Friendly**: Integrates seamlessly with GitHub Actions workflows
6. **Log Generation**: Creates detailed logs for debugging failures

## Logs

Test logs are saved to:
- `/app/logs/chromedriver_headless.log`
- `/app/logs/chromedriver_headful.log`
- `/app/logs/bravedriver_headless.log`
- `/app/logs/bravedriver_headful.log`
- `/app/logs/geckodriver_headless.log`
- `/app/logs/geckodriver_headful.log`

(Falls back to `/tmp/` if `/app/logs/` is not available)

## Integration with CI

The enhanced tests integrate with the existing GitHub Actions workflow in `.github/workflows/smoke-test.yml`:

```yaml
- name: Run browser WebDriver tests in container
  run: |
    docker run --rm \
      -e CACHE_DIR=/data \
      -v $(pwd)/data:/data \
      ${{ matrix.tag }} \
      python /app/test_browser_drivers.py
```

This ensures all Dockerfiles are tested comprehensively on every push/PR.

## Future Enhancements

Possible future improvements:
- Add performance metrics (startup time, page load time)
- Test more advanced features (downloads, file uploads, screenshots)
- Add network error simulation tests
- Test with different window sizes and resolutions
- Add mobile emulation tests
