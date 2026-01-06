# Trixie Integration Tests - Expected Behavior

## Test Execution Flow

The `docker-trixie-integration-test` job in GitHub Actions executes tests in three stages:

### Stage 1: Build and Verify
- Build Trixie Docker image with PJeOffice and PDF tools
- Log browser versions (Chrome, Firefox)
- Log Python version and key packages
- Verify oscrypto is NOT installed (security check)

### Stage 2: Run Tests Without Display
- Execute tests that don't require X11 display
- Tests included:
  - System info (Python version, packages)
  - Security checks (oscrypto absence)
  - PDF manipulation (reportlab, PyMuPDF)
  - Image manipulation (Pillow, OpenCV)
- Expected: ~10-12 tests pass, display tests skipped

### Stage 3: Run Tests With Xvfb
- Start Xvfb virtual display
- Execute display-related tests
- Tests included:
  - Xvfb process check
  - Display accessibility
  - Screenshot capability
- Expected: ~4 tests pass

### Stage 4: Run All Tests With Xvfb + Openbox
- Start Xvfb and Openbox window manager
- Execute full test suite
- Tests included: All 19 integration tests
- Expected: ~15-17 tests pass, 2-4 skipped (A1 cert tests)

## Expected Test Results

### Total Tests: 19

1. **TestSystemInfo** (3 tests)
   - ✅ Python version check (always passes)
   - ✅ Browser versions (passes in Docker)
   - ✅ Key packages installed (passes in Docker)

2. **TestDisplay** (4 tests)
   - ⚠️ Xvfb process (skips without USE_XVFB=1)
   - ⚠️ Openbox process (skips without USE_OPENBOX=1)
   - ⚠️ Display accessible (skips without USE_XVFB=1)
   - ⚠️ Screenshot capability (skips without USE_XVFB=1)

3. **TestSeleniumBase** (2 tests)
   - ✅ Chrome about:blank (passes in Docker)
   - ✅ Firefox about:blank (passes in Docker)

4. **TestImageManipulation** (2 tests)
   - ✅ Create PNG with Pillow (passes in Docker)
   - ✅ Read PNG with OpenCV (passes in Docker)

5. **TestPDFManipulation** (2 tests)
   - ✅ Generate PDF with reportlab (passes in Docker)
   - ✅ Read PDF with PyMuPDF (passes in Docker)

6. **TestA1Certificate** (4 tests)
   - ✅ OpenSSL available (always passes in Docker)
   - ✅ Cryptography PKI libs (always passes in Docker)
   - ⚠️ A1 certificate operations (skips without cert)
   - ⚠️ PDF signing with endesive (skips without cert)

7. **TestSecurity** (2 tests)
   - ✅ oscrypto not installed (always passes)
   - ✅ Required security packages (passes in Docker)

### Expected Pass Rate

- **Without display**: ~10-12 passed, 7-9 skipped
- **With Xvfb**: ~14-15 passed, 4-5 skipped
- **With Xvfb + Openbox**: ~15-17 passed, 2-4 skipped

## Failure Scenarios

### Expected Failures (Should NOT Happen)

1. **oscrypto detected**: Test fails if oscrypto package is found
   - Action: Remove oscrypto from dependencies
   
2. **Missing critical packages**: Test fails if core packages missing
   - Action: Verify requirements.txt and Dockerfile

3. **Browser not found**: Test fails if Chrome or Firefox missing
   - Action: Check Dockerfile.trixie browser installation

### Expected Skips (Normal Behavior)

1. **Display tests without Xvfb**: Tests skip gracefully
2. **A1 certificate tests**: Tests skip if cert not provided
3. **Openbox tests without Openbox**: Tests skip gracefully

## Timeout Behavior

- **Default timeout**: 300 seconds (5 minutes) per test
- **Test-specific timeout**: 60 seconds for browser tests
- **Full suite timeout**: ~180 seconds (3 minutes)

If tests timeout:
1. Check if Xvfb started properly (add sleep before tests)
2. Check if browsers are responding
3. Increase timeout if needed

## Artifact Output

Tests generate artifacts in `/data` and `/test-results`:

- `data/`: Screenshots, PDFs, test images
- `test-results/junit-*.xml`: JUnit XML test reports

## Debugging Failed Tests

### Check Browser Logs
```bash
docker run --rm -e USE_XVFB=1 rpa-worker-trixie:test \
  bash -c "sleep 3 && chrome --version && firefox --version"
```

### Check Package Installation
```bash
docker run --rm rpa-worker-trixie:test \
  pip list | grep -E "(selenium|pillow|reportlab)"
```

### Run Single Test with Verbose Output
```bash
docker run --rm -e USE_XVFB=1 rpa-worker-trixie:test \
  bash -c "sleep 3 && pytest -vvs tests/trixie_integration_test.py::TestSeleniumBase::test_chrome_about_blank"
```

## CI/CD Best Practices

1. **Always use timeouts**: Prevent hanging tests
2. **Check logs first**: Verify versions before running tests
3. **Save artifacts**: Upload test results even on failure
4. **Graceful degradation**: Tests skip rather than fail when dependencies missing
5. **Fast feedback**: Run quick tests first, slow tests later
