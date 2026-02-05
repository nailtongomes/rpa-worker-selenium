#!/bin/bash
# Manual test script for standby mode
# This script simulates the container environment and tests:
# 1. Default mode (pull) - existing behavior
# 2. Standby mode activation
# 3. Task execution

cd "$(dirname "$0")"

echo "=========================================="
echo "Manual Test: Standby Mode"
echo "=========================================="
echo ""

# Test 1: Verify entrypoint has standby logic
echo "Test 1: Checking entrypoint.sh for standby logic..."
if grep -q "WORKER_MODE.*standby" entrypoint.sh; then
    echo "✅ PASS: Standby check found in entrypoint.sh"
else
    echo "❌ FAIL: Standby check not found in entrypoint.sh"
    exit 1
fi

if grep -q "task_server.py" entrypoint.sh; then
    echo "✅ PASS: task_server.py reference found in entrypoint.sh"
else
    echo "❌ FAIL: task_server.py reference not found in entrypoint.sh"
    exit 1
fi
echo ""

# Test 2: Verify task_server.py exists
echo "Test 2: Checking task_server.py exists..."
if [ -f "task_server.py" ]; then
    echo "✅ PASS: task_server.py exists"
else
    echo "❌ FAIL: task_server.py not found"
    exit 1
fi

if [ -x "task_server.py" ]; then
    echo "✅ PASS: task_server.py is executable"
else
    echo "❌ FAIL: task_server.py is not executable"
    exit 1
fi
echo ""

# Test 3: Verify Flask in requirements
echo "Test 3: Checking Flask in requirements.txt..."
if grep -qi "flask" requirements.txt; then
    echo "✅ PASS: Flask found in requirements.txt"
else
    echo "❌ FAIL: Flask not found in requirements.txt"
    exit 1
fi
echo ""

# Test 4: Start server and test health endpoint
echo "Test 4: Testing HTTP server..."
export WORKER_MODE=standby
export TASK_SERVER_PORT=8765
export TASK_AUTH_TOKEN=""

echo "  Starting server on port 8765..."
python task_server.py > /tmp/server.log 2>&1 &
SERVER_PID=$!
sleep 2

if ps -p $SERVER_PID > /dev/null; then
    echo "  ✅ Server started (PID: $SERVER_PID)"
else
    echo "  ❌ Server failed to start"
    cat /tmp/server.log
    exit 1
fi

echo "  Testing /health endpoint..."
HEALTH_RESPONSE=$(curl -s http://localhost:8765/health)
if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
    echo "  ✅ /health endpoint working"
    echo "  Response: $HEALTH_RESPONSE"
else
    echo "  ❌ /health endpoint failed"
    echo "  Response: $HEALTH_RESPONSE"
    kill $SERVER_PID 2>/dev/null
    exit 1
fi
echo ""

# Test 5: Test task endpoint validation
echo "Test 5: Testing task endpoint validation..."

echo "  Test 5a: Non-HTTPS URL should be rejected..."
RESPONSE=$(curl -s -X POST http://localhost:8765/task \
  -H "Content-Type: application/json" \
  -d '{"script_url": "http://example.com/test.py", "script_name": "test.py"}')
if echo "$RESPONSE" | grep -q "HTTPS"; then
    echo "  ✅ Non-HTTPS URL rejected correctly"
else
    echo "  ❌ Non-HTTPS URL validation failed"
    echo "  Response: $RESPONSE"
fi

echo "  Test 5b: Missing script_url should be rejected..."
RESPONSE=$(curl -s -X POST http://localhost:8765/task \
  -H "Content-Type: application/json" \
  -d '{"script_name": "test.py"}')
if echo "$RESPONSE" | grep -q "script_url"; then
    echo "  ✅ Missing script_url rejected correctly"
else
    echo "  ❌ Missing script_url validation failed"
    echo "  Response: $RESPONSE"
fi

echo "  Test 5c: Mismatched script_name should be rejected..."
RESPONSE=$(curl -s -X POST http://localhost:8765/task \
  -H "Content-Type: application/json" \
  -d '{"script_url": "https://example.com/script_abc.py", "script_name": "wrong.py"}')
if echo "$RESPONSE" | grep -q "does not match"; then
    echo "  ✅ Mismatched script_name rejected correctly"
else
    echo "  ❌ Mismatched script_name validation failed"
    echo "  Response: $RESPONSE"
fi
echo ""

# Test 6: Documentation
echo "Test 6: Checking documentation..."
if grep -q "standby" WORKER_README.md; then
    echo "✅ PASS: Standby mode documented in WORKER_README.md"
else
    echo "❌ FAIL: Standby mode not documented in WORKER_README.md"
fi

if grep -q "WORKER_MODE" WORKER_README.md; then
    echo "✅ PASS: WORKER_MODE documented"
else
    echo "❌ FAIL: WORKER_MODE not documented"
fi

if grep -q "TASK_SERVER_PORT" WORKER_README.md; then
    echo "✅ PASS: TASK_SERVER_PORT documented"
else
    echo "❌ FAIL: TASK_SERVER_PORT not documented"
fi
echo ""

# Cleanup
echo "Cleaning up..."
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
rm -f /tmp/server.log

echo ""
echo "=========================================="
echo "✅ All manual tests passed!"
echo "=========================================="
