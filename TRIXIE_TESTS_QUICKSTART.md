# Trixie Integration Tests - Quick Start

This guide provides quick commands for running the Trixie integration tests.

## Quick Commands

### Local Testing (Host Machine)

```bash
# Run all tests (may fail if dependencies missing)
pytest -v -m "trixie and integration" tests/trixie_integration_test.py

# Run with timeout
pytest -v --timeout=180 -m "trixie and integration" tests/trixie_integration_test.py

# Run specific test class
pytest -v tests/trixie_integration_test.py::TestSystemInfo
pytest -v tests/trixie_integration_test.py::TestSecurity
pytest -v tests/trixie_integration_test.py::TestPDFManipulation

# Run using helper script
./scripts/test_trixie_local.sh
```

### Docker Testing (Full Environment)

```bash
# Build and run all tests
./scripts/test_trixie_docker.sh all

# Just build image
./scripts/test_trixie_docker.sh build

# Just run tests (requires pre-built image)
./scripts/test_trixie_docker.sh test

# Manual Docker commands
docker build -f Dockerfile.trixie \
  --build-arg BUILD_PJEOFFICE=1 \
  --build-arg ENABLE_PDF_TOOLS=1 \
  -t rpa-worker-trixie:test .

docker run --rm rpa-worker-trixie:test \
  pytest -v --timeout=180 -m "trixie and integration" \
  tests/trixie_integration_test.py

# With Xvfb + Openbox
docker run --rm \
  -e USE_XVFB=1 \
  -e USE_OPENBOX=1 \
  rpa-worker-trixie:test \
  bash -c "sleep 5 && pytest -v --timeout=180 -m 'trixie and integration' tests/trixie_integration_test.py"
```

## Test Categories

### System Tests (No Special Requirements)
```bash
pytest -v tests/trixie_integration_test.py::TestSystemInfo
pytest -v tests/trixie_integration_test.py::TestSecurity
```

### Display Tests (Requires Xvfb)
```bash
# In Docker with Xvfb
docker run --rm -e USE_XVFB=1 rpa-worker-trixie:test \
  bash -c "sleep 3 && pytest -v tests/trixie_integration_test.py::TestDisplay"
```

### Browser Tests (Requires Browsers + Drivers)
```bash
pytest -v tests/trixie_integration_test.py::TestSeleniumBase
```

### Image Tests (Requires Pillow + OpenCV)
```bash
pytest -v tests/trixie_integration_test.py::TestImageManipulation
```

### PDF Tests (Requires reportlab + PyMuPDF)
```bash
pytest -v tests/trixie_integration_test.py::TestPDFManipulation
```

### Certificate Tests (Requires A1 Certificate)
```bash
# Only if you have A1 certificate
export A1_P12_PATH=/path/to/cert.p12
export A1_P12_PASSWORD=your-password
pytest -v tests/trixie_integration_test.py::TestA1Certificate
```

## CI/CD

Tests run automatically on GitHub Actions:

- **Workflow**: `.github/workflows/smoke-test.yml`
- **Job**: `docker-trixie-integration-test`
- **Trigger**: Push to main, pull requests, manual dispatch

View results: https://github.com/nailtongomes/rpa-worker-selenium/actions

## Troubleshooting

### Tests Fail Locally
**Cause**: Missing dependencies  
**Solution**: Run in Docker or install all dependencies from `requirements.txt`

### Tests Timeout
**Cause**: Browser tests may be slow  
**Solution**: Increase timeout or skip browser tests:
```bash
pytest -v --timeout=300 -k "not selenium" tests/trixie_integration_test.py
```

### Display Tests Fail
**Cause**: Xvfb not running  
**Solution**: Use Docker with `USE_XVFB=1`

### PDF Signing Tests Skip
**Cause**: No A1 certificate provided (this is normal)  
**Solution**: Tests automatically skip if certificate not available

## More Information

- Full documentation: [tests/README.md](tests/README.md)
- Test file: [tests/trixie_integration_test.py](tests/trixie_integration_test.py)
- Dockerfile: [Dockerfile.trixie](Dockerfile.trixie)
