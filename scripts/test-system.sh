#!/bin/bash
# scripts/test-system.sh
# Comprehensive test script for LMArena AI Gateway System

set -e

# Configuration
GATEWAY_URL=${GATEWAY_URL:-"http://localhost:8080"}
FLASK_URL=${FLASK_URL:-"http://localhost:5104"}
API_KEY=${API_KEY:-""}
FLASK_API_KEY=${FLASK_API_KEY:-""}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TESTS_TOTAL=0
TESTS_PASSED=0
TESTS_FAILED=0

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

# Test helper function
run_test() {
    local test_name="$1"
    local test_command="$2"
    local expected_status="$3"
    
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    log_test "Running: $test_name"
    
    if eval "$test_command"; then
        if [ "$expected_status" = "success" ]; then
            log_info "✅ PASSED: $test_name"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            log_error "❌ FAILED: $test_name (expected failure but got success)"
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    else
        if [ "$expected_status" = "failure" ]; then
            log_info "✅ PASSED: $test_name (expected failure)"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            log_error "❌ FAILED: $test_name"
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    fi
    echo ""
}

# HTTP test helper
http_test() {
    local url="$1"
    local method="$2"
    local headers="$3"
    local data="$4"
    local expected_code="$5"
    
    local curl_cmd="curl -s -w '%{http_code}' -X $method"
    
    if [ -n "$headers" ]; then
        curl_cmd="$curl_cmd $headers"
    fi
    
    if [ -n "$data" ]; then
        curl_cmd="$curl_cmd -d '$data'"
    fi
    
    curl_cmd="$curl_cmd '$url' -o /tmp/test_response.json"
    
    local response_code=$(eval "$curl_cmd")
    
    if [ "$response_code" = "$expected_code" ]; then
        return 0
    else
        log_error "Expected HTTP $expected_code, got $response_code"
        if [ -f "/tmp/test_response.json" ]; then
            log_error "Response: $(cat /tmp/test_response.json)"
        fi
        return 1
    fi
}

echo "=========================================="
echo "  LMArena AI Gateway System Test Suite"
echo "=========================================="
echo "Gateway URL: $GATEWAY_URL"
echo "Flask URL: $FLASK_URL"
echo "=========================================="
echo ""

# Test 1: Health Checks
log_info "Testing Health Endpoints..."

run_test "PHP Gateway Health Check" \
    "http_test '$GATEWAY_URL/health' 'GET' '' '' '200'" \
    "success"

run_test "Flask Services Health Check" \
    "http_test '$FLASK_URL/health' 'GET' '' '' '200'" \
    "success"

# Test 2: Provider Status
log_info "Testing Provider Status..."

run_test "Provider Status Endpoint" \
    "http_test '$GATEWAY_URL/providers/status' 'GET' '' '' '200'" \
    "success"

# Test 3: Session Management
log_info "Testing Session Management..."

# Generate test session data
TEST_SESSION_ID=$(uuidgen 2>/dev/null || echo "550e8400-e29b-41d4-a716-446655440000")
TEST_MESSAGE_ID=$(uuidgen 2>/dev/null || echo "6ba7b810-9dad-11d1-80b4-00c04fd430c8")
TEST_SESSION_NAME="test-session-$(date +%s)"

SESSION_DATA="{\"domain\":\"lmarena.ai\",\"session_name\":\"$TEST_SESSION_NAME\",\"session_id\":\"$TEST_SESSION_ID\",\"message_id\":\"$TEST_MESSAGE_ID\"}"

run_test "Session Registration" \
    "http_test '$GATEWAY_URL/session/register' 'POST' '-H \"Content-Type: application/json\"' '$SESSION_DATA' '200'" \
    "success"

run_test "Session List" \
    "http_test '$GATEWAY_URL/session/list' 'GET' '' '' '200'" \
    "success"

run_test "Session List with Domain Filter" \
    "http_test '$GATEWAY_URL/session/list?domain=lmarena.ai' 'GET' '' '' '200'" \
    "success"

HEARTBEAT_DATA="{\"domain\":\"lmarena.ai\",\"session_name\":\"$TEST_SESSION_NAME\"}"

run_test "Session Heartbeat" \
    "http_test '$GATEWAY_URL/session/heartbeat' 'POST' '-H \"Content-Type: application/json\"' '$HEARTBEAT_DATA' '200'" \
    "success"

# Test 4: Userscript Generation
log_info "Testing Userscript Generation..."

run_test "Basic Userscript Generation" \
    "http_test '$GATEWAY_URL/userscript/generate?session_name=$TEST_SESSION_NAME' 'GET' '' '' '200'" \
    "success"

if [ -n "$FLASK_API_KEY" ]; then
    run_test "Advanced Userscript Generation" \
        "http_test '$FLASK_URL/userscript/advanced-generate?session_name=$TEST_SESSION_NAME' 'GET' '-H \"Authorization: Bearer $FLASK_API_KEY\"' '' '200'" \
        "success"
else
    log_warn "Skipping advanced userscript test (no Flask API key provided)"
fi

# Test 5: Analytics (if Flask API key is available)
if [ -n "$FLASK_API_KEY" ]; then
    log_info "Testing Analytics Endpoints..."
    
    run_test "Session Analytics" \
        "http_test '$FLASK_URL/analytics/sessions' 'GET' '-H \"Authorization: Bearer $FLASK_API_KEY\"' '' '200'" \
        "success"
else
    log_warn "Skipping analytics tests (no Flask API key provided)"
fi

# Test 6: API Validation
log_info "Testing API Validation..."

run_test "Invalid Session Registration (missing fields)" \
    "http_test '$GATEWAY_URL/session/register' 'POST' '-H \"Content-Type: application/json\"' '{\"domain\":\"lmarena.ai\"}' '400'" \
    "success"

run_test "Invalid Domain" \
    "http_test '$GATEWAY_URL/session/register' 'POST' '-H \"Content-Type: application/json\"' '{\"domain\":\"invalid.com\",\"session_name\":\"test\",\"session_id\":\"$TEST_SESSION_ID\",\"message_id\":\"$TEST_MESSAGE_ID\"}' '400'" \
    "success"

run_test "Invalid Session Name Format" \
    "http_test '$GATEWAY_URL/session/register' 'POST' '-H \"Content-Type: application/json\"' '{\"domain\":\"lmarena.ai\",\"session_name\":\"invalid session name!\",\"session_id\":\"$TEST_SESSION_ID\",\"message_id\":\"$TEST_MESSAGE_ID\"}' '400'" \
    "success"

# Test 7: OpenAI API Compatibility (basic structure test)
log_info "Testing OpenAI API Compatibility..."

CHAT_DATA="{\"model\":\"gpt-4\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"stream\":false}"
HEADERS="-H \"Content-Type: application/json\" -H \"X-Session-Name: $TEST_SESSION_NAME\" -H \"X-Target-Domain: lmarena.ai\""

if [ -n "$API_KEY" ]; then
    HEADERS="$HEADERS -H \"Authorization: Bearer $API_KEY\""
fi

# Note: This test might fail if LMArenaBridge is not running, which is expected
run_test "Chat Completions Endpoint Structure" \
    "http_test '$GATEWAY_URL/v1/chat/completions' 'POST' '$HEADERS' '$CHAT_DATA' '503'" \
    "success"

run_test "Models Endpoint" \
    "http_test '$GATEWAY_URL/v1/models' 'GET' '$HEADERS' '' '503'" \
    "success"

# Test 8: Cleanup
log_info "Cleaning up test data..."

run_test "Session Deletion" \
    "http_test '$GATEWAY_URL/session/lmarena.ai/$TEST_SESSION_NAME' 'DELETE' '' '' '200'" \
    "success"

# Test 9: Performance Test (basic)
log_info "Running basic performance test..."

PERF_START=$(date +%s%N)
for i in {1..10}; do
    curl -s "$GATEWAY_URL/health" > /dev/null
done
PERF_END=$(date +%s%N)
PERF_DURATION=$(( (PERF_END - PERF_START) / 1000000 ))

log_info "10 health check requests completed in ${PERF_DURATION}ms"
if [ $PERF_DURATION -lt 5000 ]; then
    log_info "✅ Performance test passed (< 5 seconds)"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    log_error "❌ Performance test failed (>= 5 seconds)"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
TESTS_TOTAL=$((TESTS_TOTAL + 1))

# Test Results Summary
echo ""
echo "=========================================="
echo "           TEST RESULTS SUMMARY"
echo "=========================================="
echo "Total Tests: $TESTS_TOTAL"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Some tests failed. Check the output above for details.${NC}"
    exit 1
fi
