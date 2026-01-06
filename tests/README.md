# RPA Worker Selenium - Integration Tests

This directory contains integration tests for the RPA Worker Selenium project.

## Test Structure

### `trixie_integration_test.py`

Comprehensive integration tests specifically for `Dockerfile.trixie` image. These tests are designed to be:
- **Deterministic**: Reproducible results across runs
- **Fast**: Complete in < 2-3 minutes
- **Graceful**: Handle missing dependencies with proper skips
- **Comprehensive**: Cover all major functionality

#### Test Coverage

1. **System Information**
   - Python version (3.12+)
   - Browser versions (Chrome, Firefox)
   - Required packages installed

2. **Display and Window Management**
   - Xvfb process running
   - Openbox process running
   - X11 display accessibility
   - Screenshot capability

3. **SeleniumBase**
   - Chrome with about:blank
   - Firefox with about:blank

4. **Image Manipulation**
   - PNG creation with Pillow
   - PNG reading with OpenCV
   - Dimension verification

5. **PDF Manipulation**
   - PDF generation with reportlab
   - PDF reading with PyMuPDF
   - Text extraction

6. **A1 Certificate (Conditional)**
   - OpenSSL availability
   - Cryptography PKI libs
   - Certificate operations (if cert available)
   - PDF signing with endesive (if cert available)

7. **Security Checks**
   - Verify oscrypto is NOT installed
   - Required security packages present

## Running Tests

### Prerequisites

```bash
# Install test dependencies
pip install pytest pytest-timeout

# Or install all dependencies
pip install -r requirements.txt
```

### Local Execution

#### Run all Trixie integration tests

```bash
pytest -v -m "trixie and integration" tests/trixie_integration_test.py
```

#### Run with timeout (recommended)

```bash
pytest -v --timeout=180 -m "trixie and integration" tests/trixie_integration_test.py
```

#### Run specific test classes

```bash
# System info only
pytest -v tests/trixie_integration_test.py::TestSystemInfo

# Display tests only (requires Xvfb)
pytest -v tests/trixie_integration_test.py::TestDisplay

# SeleniumBase tests only
pytest -v tests/trixie_integration_test.py::TestSeleniumBase

# Image manipulation
pytest -v tests/trixie_integration_test.py::TestImageManipulation

# PDF manipulation
pytest -v tests/trixie_integration_test.py::TestPDFManipulation

# A1 certificate (requires cert)
pytest -v tests/trixie_integration_test.py::TestA1Certificate

# Security checks
pytest -v tests/trixie_integration_test.py::TestSecurity
```

#### Run specific tests

```bash
# Test specific functionality
pytest -v tests/trixie_integration_test.py::TestSystemInfo::test_python_version
pytest -v tests/trixie_integration_test.py::TestSeleniumBase::test_chrome_about_blank
```

### Docker Execution

#### Build test image

```bash
docker build -f Dockerfile.trixie \
  --build-arg BUILD_PJEOFFICE=1 \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t rpa-worker-trixie:test .
```

#### Run tests without display

```bash
docker run --rm \
  rpa-worker-trixie:test \
  pytest -v --timeout=180 -m "trixie and integration" \
  tests/trixie_integration_test.py \
  -k "not (xvfb or openbox or display or screenshot)"
```

#### Run tests with Xvfb

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e DISPLAY=:99 \
  rpa-worker-trixie:test \
  bash -c "sleep 3 && pytest -v --timeout=180 -m 'trixie and integration' tests/trixie_integration_test.py"
```

#### Run tests with Xvfb + Openbox

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e DISPLAY=:99 \
  rpa-worker-trixie:test \
  bash -c "sleep 5 && pytest -v --timeout=180 -m 'trixie and integration' tests/trixie_integration_test.py"
```

#### Run with A1 certificate (optional)

```bash
docker run --rm \
  -e USE_XVFB=1 \
  -e A1_P12_PATH=/certs/certificate.p12 \
  -e A1_P12_PASSWORD=your-password \
  -v /path/to/certs:/certs:ro \
  rpa-worker-trixie:test \
  bash -c "sleep 3 && pytest -v --timeout=180 -m 'trixie and integration' tests/trixie_integration_test.py"
```

#### Run with artifacts saved

```bash
mkdir -p test-results data

docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  -e CACHE_DIR=/data \
  -v $(pwd)/data:/data \
  -v $(pwd)/test-results:/test-results \
  rpa-worker-trixie:test \
  bash -c "sleep 5 && pytest -v --timeout=180 --junitxml=/test-results/junit.xml -m 'trixie and integration' tests/trixie_integration_test.py"

# View results
cat test-results/junit.xml
ls -la data/
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DISPLAY` | `:99` | X11 display number |
| `USE_XVFB` | `0` | Enable Xvfb virtual display |
| `USE_OPENBOX` | `0` | Enable Openbox window manager |
| `SCREEN_WIDTH` | `1366` | Screen width |
| `SCREEN_HEIGHT` | `768` | Screen height |
| `A1_P12_PATH` | - | Path to A1 certificate (.p12 file) |
| `A1_P12_PASSWORD` | - | Password for A1 certificate |
| `CACHE_DIR` | `/data` | Directory for test artifacts |

## Pytest Markers

Tests are marked with pytest markers for selective execution:

- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.trixie` - Trixie-specific tests
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.requires_display` - Tests requiring X11 display
- `@pytest.mark.requires_cert` - Tests requiring A1 certificate

### Examples

```bash
# Run only integration tests
pytest -m integration

# Run only trixie tests
pytest -m trixie

# Run trixie integration tests
pytest -m "trixie and integration"

# Exclude slow tests
pytest -m "trixie and integration and not slow"
```

## CI/CD Integration

Tests run automatically in GitHub Actions via `.github/workflows/smoke-test.yml`:

- **Job**: `docker-trixie-integration-test`
- **Triggers**: Push to main, pull requests, manual dispatch
- **Stages**:
  1. Build Trixie image with test dependencies
  2. Log versions and verify packages
  3. Run tests without display
  4. Run tests with Xvfb
  5. Run tests with Xvfb + Openbox
  6. Upload test results and artifacts

## Test Output

### Console Output

Tests provide detailed console output with:
- ✓ markers for passed tests
- ✗ markers for failed tests
- ⚠ markers for skipped tests
- Detailed information about versions, paths, and results

### Artifacts

Tests generate artifacts in `CACHE_DIR`:
- Screenshots (PNG files)
- Generated PDFs
- Test images
- Signed PDFs (if certificate available)

### JUnit XML

When running with `--junitxml`, tests generate XML reports compatible with CI/CD systems:

```bash
pytest --junitxml=test-results/junit.xml tests/trixie_integration_test.py
```

## Troubleshooting

### Tests fail with "Display not accessible"

**Solution**: Make sure `USE_XVFB=1` is set and give Xvfb time to start:

```bash
docker run --rm -e USE_XVFB=1 rpa-worker-trixie:test \
  bash -c "sleep 3 && pytest ..."
```

### Tests timeout

**Solution**: Increase timeout or use faster test selection:

```bash
# Increase timeout
pytest --timeout=300 ...

# Run faster subset
pytest -k "not slow" ...
```

### A1 certificate tests fail

**Solution**: These tests are optional and skip if certificate not available. To enable:

```bash
export A1_P12_PATH=/path/to/cert.p12
export A1_P12_PASSWORD=your-password
pytest tests/trixie_integration_test.py::TestA1Certificate
```

### oscrypto detected error

**Solution**: This is intentional - the test fails if oscrypto is found. Remove it:

```bash
pip uninstall oscrypto -y
```

## Contributing

When adding new tests:

1. Follow the existing test structure
2. Add appropriate pytest markers
3. Make tests deterministic
4. Handle missing dependencies gracefully
5. Keep tests fast (< 60s per test class)
6. Document required environment variables
7. Update this README

## References

- [pytest documentation](https://docs.pytest.org/)
- [pytest-timeout](https://pypi.org/project/pytest-timeout/)
- [SeleniumBase](https://seleniumbase.io/)
- [Dockerfile.trixie](../Dockerfile.trixie)
