#!/bin/bash
# Test runner for IPO Sell-Buy-Trigger mode

echo "========================================================================"
echo "IPO SELL-BUY-TRIGGER MODE - TEST SUITE"
echo "========================================================================"
echo ""

# Change to project root
cd "$(dirname "$0")/.." || exit 1

# Run main test suite
echo "Running main test suite..."
python3 tests/test_ipo_sell_buy_trigger.py
MAIN_EXIT=$?

echo ""
echo "========================================================================"
echo ""

# Run compatibility tests
echo "Running compatibility tests..."
python3 tests/test_mode_compatibility.py
COMPAT_EXIT=$?

echo ""
echo "========================================================================"
echo "OVERALL TEST RESULTS"
echo "========================================================================"

if [ $MAIN_EXIT -eq 0 ] && [ $COMPAT_EXIT -eq 0 ]; then
    echo "✅ ALL TESTS PASSED"
    exit 0
else
    echo "❌ SOME TESTS FAILED"
    [ $MAIN_EXIT -ne 0 ] && echo "  - Main test suite failed"
    [ $COMPAT_EXIT -ne 0 ] && echo "  - Compatibility tests failed"
    exit 1
fi
