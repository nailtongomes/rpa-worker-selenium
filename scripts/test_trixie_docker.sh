#!/bin/bash
# Docker test script for Trixie integration tests
# Usage: ./scripts/test_trixie_docker.sh [build|test|all]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

IMAGE_NAME="rpa-worker-trixie:test"
ACTION="${1:-all}"

echo "=========================================="
echo "Trixie Integration Tests - Docker Runner"
echo "=========================================="

build_image() {
    echo ""
    echo -e "${BLUE}Building Docker image...${NC}"
    docker build -f Dockerfile.trixie \
        --build-arg BUILD_PJEOFFICE=1 \
        --build-arg ENABLE_PDF_TOOLS=1 \
        -t "$IMAGE_NAME" .
    
    echo -e "${GREEN}✓ Image built successfully${NC}"
}

log_versions() {
    echo ""
    echo -e "${BLUE}Logging versions and package info...${NC}"
    docker run --rm "$IMAGE_NAME" bash -c "
        echo '=== System Information ===' && \
        python --version && \
        chrome --version && \
        firefox --version && \
        chromedriver --version && \
        geckodriver --version && \
        openssl version && \
        echo '=== Key Package Versions ===' && \
        pip show pytest selenium seleniumbase pillow opencv-python reportlab PyMuPDF endesive cryptography | grep -E '^(Name|Version):' && \
        echo '=== Verify oscrypto is NOT installed ===' && \
        (pip show oscrypto && echo 'ERROR: oscrypto found!' && exit 1) || echo 'OK: oscrypto not installed'
    "
}

run_tests() {
    echo ""
    echo -e "${BLUE}Creating test directories...${NC}"
    mkdir -p data test-results
    chmod 777 data test-results
    
    echo ""
    echo -e "${BLUE}Running tests without display...${NC}"
    docker run --rm \
        -e CACHE_DIR=/data \
        -v "$(pwd)/data:/data" \
        -v "$(pwd)/test-results:/test-results" \
        "$IMAGE_NAME" \
        bash -c "pytest -v --timeout=180 --junitxml=/test-results/junit-no-display.xml -m 'trixie and integration' tests/trixie_integration_test.py -k 'not (xvfb or openbox or display or screenshot)'" || true
    
    echo ""
    echo -e "${BLUE}Running tests with Xvfb...${NC}"
    docker run --rm \
        -e USE_XVFB=1 \
        -e DISPLAY=:99 \
        -e CACHE_DIR=/data \
        -v "$(pwd)/data:/data" \
        -v "$(pwd)/test-results:/test-results" \
        "$IMAGE_NAME" \
        bash -c "sleep 3 && pytest -v --timeout=180 --junitxml=/test-results/junit-xvfb.xml -m 'trixie and integration' tests/trixie_integration_test.py::TestDisplay" || true
    
    echo ""
    echo -e "${BLUE}Running tests with Xvfb + Openbox...${NC}"
    docker run --rm \
        -e USE_XVFB=1 \
        -e USE_OPENBOX=1 \
        -e DISPLAY=:99 \
        -e CACHE_DIR=/data \
        -v "$(pwd)/data:/data" \
        -v "$(pwd)/test-results:/test-results" \
        "$IMAGE_NAME" \
        bash -c "sleep 5 && pytest -v --timeout=180 --junitxml=/test-results/junit-full.xml -m 'trixie and integration' tests/trixie_integration_test.py" || true
}

display_results() {
    echo ""
    echo -e "${BLUE}=== Test Results Summary ===${NC}"
    
    for file in test-results/*.xml; do
        if [ -f "$file" ]; then
            echo ""
            echo "File: $(basename "$file")"
            
            tests=$(grep -oP 'tests="\K[0-9]+' "$file" | head -1 || echo "0")
            failures=$(grep -oP 'failures="\K[0-9]+' "$file" | head -1 || echo "0")
            errors=$(grep -oP 'errors="\K[0-9]+' "$file" | head -1 || echo "0")
            skipped=$(grep -oP 'skipped="\K[0-9]+' "$file" | head -1 || echo "0")
            
            echo "  Tests: $tests"
            echo "  Failures: $failures"
            echo "  Errors: $errors"
            echo "  Skipped: $skipped"
            
            if [ "$failures" -eq 0 ] && [ "$errors" -eq 0 ]; then
                echo -e "  ${GREEN}✓ PASSED${NC}"
            else
                echo -e "  ${RED}✗ FAILED${NC}"
            fi
        fi
    done
    
    echo ""
    echo "Test artifacts saved in:"
    echo "  - $(pwd)/test-results/ (JUnit XML)"
    echo "  - $(pwd)/data/ (screenshots, PDFs, etc.)"
}

# Main execution
case "$ACTION" in
    build)
        build_image
        log_versions
        ;;
    test)
        run_tests
        display_results
        ;;
    all)
        build_image
        log_versions
        run_tests
        display_results
        ;;
    *)
        echo "Usage: $0 [build|test|all]"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}=========================================="
echo "✓ Done!"
echo "==========================================${NC}"
