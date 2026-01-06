#!/bin/bash
# Local test script for Trixie integration tests
# Usage: ./scripts/test_trixie_local.sh [test-pattern]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Trixie Integration Tests - Local Runner"
echo "=========================================="

# Check if pytest is installed
if ! python -m pytest --version &>/dev/null; then
    echo -e "${YELLOW}pytest not found. Installing...${NC}"
    pip install pytest pytest-timeout
fi

# Default test pattern
TEST_PATTERN="${1:-tests/trixie_integration_test.py}"

echo ""
echo -e "${GREEN}Running tests matching: ${TEST_PATTERN}${NC}"
echo ""

# Run tests
python -m pytest \
    -v \
    --timeout=180 \
    -m "trixie and integration" \
    "$TEST_PATTERN"

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
else
    echo -e "${RED}✗ Some tests failed (exit code: $EXIT_CODE)${NC}"
    echo ""
    echo "Note: Tests may fail if dependencies are missing."
    echo "Run inside Trixie Docker container for full environment."
fi

exit $EXIT_CODE
