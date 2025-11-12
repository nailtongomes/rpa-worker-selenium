# Full Smoke Test Documentation

## Overview

The `full_smoke_test.py` script provides comprehensive system integrity validation for the RPA Worker Selenium Docker image. It performs extensive checks beyond the basic `smoke_test.py` to ensure all components are working correctly.

## Features

### Comprehensive Validation
- **Python Environment**: Version compatibility (3.8+)
- **Dependencies**: All core packages (selenium, seleniumbase, requests, beautifulsoup4, pandas, openpyxl, PIL, opencv, pyautogui, psutil)
- **Browser Drivers**: ChromeDriver, GeckoDriver availability and version checking
- **Selenium**: Chrome, Firefox, and Brave browser functionality (configurable)
- **SeleniumBase**: Undetected ChromeDriver mode
- **Fallback**: Requests library for basic HTTP validation
- **Script System**: Downloader functionality and helper scripts integration
- **Environment**: Variable configuration and validation
- **Processes**: Health checks for Xvfb, PJeOffice, and screen recording
- **System**: Filesystem operations and network connectivity

### Reporting
- Detailed JSON reports with timestamps
- Individual test results with pass/fail status
- Overall success rate calculation
- Failed test summaries
- Comprehensive test details

### Configuration
All aspects configurable via environment variables:
- `TARGET_URL`: URL for browser validation tests
- `CACHE_DIR`: Directory for outputs and reports
- `TEST_ALL_BROWSERS`: Enable testing of all available browsers
- `CHECK_PROCESSES`: Enable process health checks
- `VERBOSE`: Enable detailed debug output

## Usage

### Basic Usage

```bash
# Run with defaults
python full_smoke_test.py

# Run with custom URL
TARGET_URL=https://example.com python full_smoke_test.py

# Run with verbose output
VERBOSE=1 python full_smoke_test.py
```

### Docker Usage

```bash
# Basic Docker run
docker run --rm \
  -e TARGET_URL=https://example.com \
  -e CACHE_DIR=/data \
  -v $(pwd)/data:/data \
  rpa-worker-selenium \
  python /app/full_smoke_test.py

# With all features enabled
docker run --rm \
  -e USE_XVFB=1 \
  -e CHECK_PROCESSES=1 \
  -e TEST_ALL_BROWSERS=1 \
  -e TARGET_URL=https://example.com \
  -e CACHE_DIR=/data \
  -v $(pwd)/data:/data \
  rpa-worker-selenium \
  python /app/full_smoke_test.py

# With PJeOffice and process checks
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e USE_PJEOFFICE=1 \
  -e CHECK_PROCESSES=1 \
  -e TARGET_URL=https://example.com \
  -e CACHE_DIR=/data \
  -v $(pwd)/data:/data \
  rpa-worker-selenium-pje \
  bash -c "sleep 5 && python /app/full_smoke_test.py"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TARGET_URL` | https://example.com | URL to test during browser validation |
| `CACHE_DIR` | /data | Directory to save test outputs and reports |
| `TEST_ALL_BROWSERS` | 0 | Test all available browsers (set to 1 to enable) |
| `CHECK_PROCESSES` | 0 | Check if Xvfb and PJeOffice processes are alive (set to 1 to enable) |
| `VERBOSE` | 0 | Enable verbose output (set to 1 to enable) |

## Test Categories

### 1. Python Environment
- **python_version**: Validates Python 3.8+ compatibility

### 2. Core Imports
- **import_selenium**: Selenium WebDriver
- **import_seleniumbase**: SeleniumBase
- **import_requests**: Requests library
- **import_beautifulsoup4**: BeautifulSoup4
- **import_pandas**: Pandas
- **import_openpyxl**: OpenPyXL
- **import_PIL**: Pillow
- **import_cv2**: OpenCV
- **import_pyautogui**: PyAutoGUI
- **import_psutil**: psutil

### 3. Browser Drivers
- **chromedriver_available**: ChromeDriver availability and version
- **geckodriver_available**: GeckoDriver availability and version (optional)

### 4. Browser Functionality
- **chrome_selenium**: Selenium with Chrome
- **firefox_selenium**: Selenium with Firefox (optional, when TEST_ALL_BROWSERS=1)
- **brave_selenium**: Selenium with Brave (optional, when TEST_ALL_BROWSERS=1)
- **seleniumbase**: SeleniumBase functionality

### 5. Fallback
- **requests_fallback**: Basic HTTP functionality with requests

### 6. Script System
- **script_downloader**: Script downloader functionality
- **helper_scripts**: Helper scripts integration

### 7. Environment
- **environment_variables**: Environment variable configuration

### 8. Process Checks (when CHECK_PROCESSES=1)
- **xvfb_process**: Xvfb virtual display
- **pjeoffice_process**: PJeOffice service

### 9. System
- **filesystem_operations**: File read/write operations
- **network_connectivity**: Network accessibility

## Output

### Console Output
The script provides real-time feedback with:
- Timestamp for each test
- Pass/fail status with ✓/✗ symbols
- Detailed error messages for failures
- Summary statistics
- Failed test listing

Example:
```
[2025-11-12 18:03:20] [INFO] ================================================================================
[2025-11-12 18:03:20] [INFO] FULL SMOKE TEST - RPA Worker Selenium
[2025-11-12 18:03:20] [INFO] ================================================================================
[2025-11-12 18:03:20] [INFO] Target URL: https://example.com
[2025-11-12 18:03:20] [INFO] Cache Directory: data
[2025-11-12 18:03:20] [INFO] ================================================================================

[2025-11-12 18:03:20] [INFO] Testing Python version...
[2025-11-12 18:03:20] [INFO] ✓ PASS: python_version - Python 3.12 is compatible
...
[2025-11-12 18:03:21] [INFO] Total Tests: 20
[2025-11-12 18:03:21] [INFO] Passed: 18
[2025-11-12 18:03:21] [INFO] Failed: 2
[2025-11-12 18:03:21] [INFO] Success Rate: 90.0%
```

### JSON Report
Generated at `${CACHE_DIR}/full_smoke_test_report_${timestamp}.json`

Structure:
```json
{
  "timestamp": "20251112_180321",
  "total_tests": 20,
  "passed": 18,
  "failed": 2,
  "success_rate": 90.0,
  "tests": {
    "test_name": {
      "passed": true,
      "details": "Test details",
      "timestamp": "2025-11-12T18:03:20.861473"
    }
  }
}
```

## Exit Codes

- **0**: All tests passed
- **1**: One or more tests failed

## Best Practices

1. **Development**: Run with `VERBOSE=1` for detailed debugging
2. **CI/CD**: Use default settings for consistent validation
3. **Production**: Run periodically to validate system integrity
4. **Docker**: Always mount a volume to `CACHE_DIR` to preserve reports
5. **Process Checks**: Use `CHECK_PROCESSES=1` only when processes are actually started

## Integration with CI/CD

The script is designed for easy integration with CI/CD pipelines:

```yaml
# GitHub Actions example
- name: Run Full Smoke Test
  run: |
    docker run --rm \
      -e TARGET_URL=https://example.com \
      -e CACHE_DIR=/data \
      -v $(pwd)/data:/data \
      rpa-worker-selenium \
      python /app/full_smoke_test.py
```

## Troubleshooting

### PyAutoGUI Import Error
If `import_pyautogui` fails with DISPLAY error:
- Set `DISPLAY=:99` environment variable
- Ensure Xvfb is running if using GUI features

### Browser Tests Fail
If browser tests fail:
- Verify browser and driver are installed
- Check ChromeDriver/GeckoDriver version compatibility
- Ensure headless mode is properly configured

### Process Checks Fail
If process checks fail:
- Verify services are started before running test
- Add sleep delay before test execution: `bash -c "sleep 5 && python /app/full_smoke_test.py"`
- Check service logs for startup issues

### Network Tests Fail
If network tests fail:
- Verify internet connectivity
- Check firewall/proxy settings
- Use accessible test URLs

## Differences from Basic Smoke Test

| Feature | smoke_test.py | full_smoke_test.py |
|---------|---------------|-------------------|
| Dependency validation | No | Yes (10+ packages) |
| Driver version check | No | Yes |
| Multiple browsers | No | Yes (configurable) |
| Process monitoring | Basic | Comprehensive |
| Report format | Simple | Detailed JSON |
| Configuration | Limited | Extensive |
| Exit codes | Basic | Detailed |
| Test count | ~5 | 20+ |
| Verbose mode | No | Yes |

## Unit Tests

The script includes comprehensive unit tests in `test_full_smoke_test.py`:
- Module import validation
- Function testing (log, record_test, etc.)
- Configuration testing
- Report generation validation

Run unit tests:
```bash
python test_full_smoke_test.py
```

## Version History

### v1.0.0 (2025-11-12)
- Initial release
- 20+ comprehensive test cases
- JSON report generation
- Configurable via environment variables
- Docker-ready
- CI/CD integration support
