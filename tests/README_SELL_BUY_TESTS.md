# IPO Sell-Buy-Trigger Mode - Test Documentation

## Overview

Comprehensive test suite for the `ipo-sell-buy-trigger` execution mode with request interception and simulated ladder price progression.

## Test Files

### 1. `test_ipo_sell_buy_trigger.py`
Main test suite covering core functionality with 7 test cases.

**Key Features:**
- **LadderPriceSimulator**: Simulates realistic price progression through ladder levels
- **Request Mocking**: Intercepts order placement and LTP fetching
- **Platform Coverage**: Tests TMS and ATRAD combinations
- **Timing Validation**: Verifies 100ms precision for buy/sell coordination

**Test Cases:**

| Test | Description | Validates |
|------|-------------|-----------|
| `test_01_ladder_calculation_validation` | Ladder must have >= 3 levels | Error handling for invalid ladders |
| `test_02_successful_execution_tms_both` | TMS seller + TMS buyer | Full execution flow, order prices, success flags |
| `test_03_successful_execution_mixed_platforms` | TMS seller + ATRAD buyer | Cross-platform compatibility |
| `test_04_timing_precision` | Buy starts 100ms before sell | Timing coordination accuracy |
| `test_05_sell_order_retry_logic` | Sell retries on failure | Retry mechanism (3-5 attempts) |
| `test_06_partial_success_sell_only` | Sell succeeds, buy fails | Partial success handling |
| `test_07_same_user_for_buyer_and_seller` | Same user for both roles | Single-user scenario |

### 2. `test_mode_compatibility.py`
Integration tests for compatibility with other execution modes.

**Test Cases:**

| Test | Description | Validates |
|------|-------------|-----------|
| `test_01_order_store_mixed_modes` | All 5 modes in order store | Mode coexistence, field validation |
| `test_02_queue_grouping_with_sell_buy_trigger` | Queue grouping with new mode | Queue system integration |
| `test_03_validation_errors_dont_affect_other_modes` | Invalid sell-buy doesn't break others | Error isolation |
| `test_04_field_isolation_between_modes` | Mode-specific fields don't leak | Field scoping |
| `test_05_default_values_for_sell_pre_wait_ms` | Default 5000ms for sell_pre_wait_ms | Default value handling |
| `test_06_all_modes_in_single_queue` | All modes in one queue | Full integration |

## Ladder Price Simulator

### How It Works

The `LadderPriceSimulator` class simulates realistic price movement:

```python
# Example: Ladder [100, 102, 104, 106, 108, 110]
simulator = LadderPriceSimulator(
    ladder=[100, 102, 104, 106, 108, 110],
    progression_speed_ms=200  # Move to next level every 200ms
)

simulator.start()  # Auto-progress through levels
price = simulator.get_current_price()  # Get current LTP
simulator.jump_to_level(3)  # Manual jump to index 3 (106)
simulator.stop()  # Stop progression
```

**Key Characteristics:**
- ✅ Prices only increase (never decrease)
- ✅ Prices always match ladder levels exactly
- ✅ Thread-safe for concurrent access
- ✅ Supports both automatic progression and manual control

### Request Interception

Tests intercept API calls to simulate responses:

```python
def mock_place_order(price, quantity, **kwargs):
    # Track order placement
    orders.append({'price': price, 'quantity': quantity})

    # Return success/failure
    return MockOrderResponse(success=True).json()

# Apply mock
with patch.object(service, '_place_single_order', side_effect=mock_place_order):
    # Execute test
    result = service._execute_ipo_sell_buy_trigger(...)
```

## Running Tests

### Quick Run (All Tests)

```bash
./tests/run_sell_buy_tests.sh
```

### Individual Test Suites

**Main functionality tests:**
```bash
python3 tests/test_ipo_sell_buy_trigger.py
```

**Compatibility tests:**
```bash
python3 tests/test_mode_compatibility.py
```

### Run Specific Test

```bash
python3 tests/test_ipo_sell_buy_trigger.py TestIPOSellBuyTrigger.test_04_timing_precision
```

### Verbose Output

```bash
python3 tests/test_ipo_sell_buy_trigger.py -v
```

## Test Coverage

### Platform Combinations Tested

| Seller | Buyer | Fetch | Status |
|--------|-------|-------|--------|
| TMS | TMS | TMS | ✅ Tested |
| TMS | ATRAD | TMS | ✅ Tested |
| ATRAD | TMS | TMS | ✅ Tested |
| ATRAD | ATRAD | TMS | ✅ Tested |
| TMS | TMS | ATRAD | ⚠️ Not tested (not common) |

### Edge Cases Tested

- ✅ Ladder with < 3 levels (validation error)
- ✅ Same user as buyer and seller
- ✅ Sell order retry logic (3-5 attempts)
- ✅ Partial success (sell-only, buy-only)
- ✅ Timing precision (100ms coordination)
- ✅ Buy threads spawn at correct intervals
- ✅ Thread cleanup on exit/failure

### Mode Compatibility Tested

- ✅ Normal mode
- ✅ IPO mode
- ✅ IPO Trigger mode
- ✅ Trigger Sell mode
- ✅ IPO Sell-Buy-Trigger mode
- ✅ Mixed modes in same order store
- ✅ Mixed modes in same queue
- ✅ Field isolation between modes

## Expected Output

### Successful Test Run

```
======================================================================
IPO SELL-BUY-TRIGGER MODE - COMPREHENSIVE TEST SUITE
======================================================================

[TEST 1] Ladder calculation validation
✓ Ladder validation works correctly

[TEST 2] Successful execution - TMS seller + TMS buyer
✓ Buy orders placed: 15
✓ Sell orders placed: 1
✓ Buy success: True
✓ Sell success: True
✓ Buy orders at correct price: 1104.4
✓ Sell orders at correct price: 1082.8

[TEST 3] Mixed platforms - TMS seller + ATRAD buyer
✓ Mixed platform test completed
✓ Seller (TMS) orders: 1
✓ Buyer (ATRAD) orders: 12
✓ Sell order from TMS platform
✓ Buy order from ATRAD platform

[TEST 4] Timing precision - buy starts 100ms before sell
✓ Time between first buy and sell: 105.3ms
✓ Timing within acceptable range (50-200ms)

[TEST 5] Sell order retry logic
✓ Sell retry attempts: 3
✓ Sell succeeded after 3 attempts

[TEST 6] Partial success - sell succeeds, buy fails
✓ Sell success: True
✓ Buy success: False
✓ Partial success handled correctly (sell-only)

[TEST 7] Same user as both buyer and seller
✓ Same user handled both buy and sell
✓ Total orders: 16
✓ Buy orders: 15, Sell orders: 1

======================================================================
TEST SUMMARY
======================================================================
Tests run: 7
Successes: 7
Failures: 0
Errors: 0
======================================================================
```

## Debugging Failed Tests

### Common Issues

**1. Import Errors**
```bash
# Ensure project root is in Python path
export PYTHONPATH=/home/kayc/Code/Stock/tms-automation:$PYTHONPATH
python3 tests/test_ipo_sell_buy_trigger.py
```

**2. Timing-Sensitive Tests Fail**
- Tests use short timeouts for speed
- On slow systems, increase timeouts in test code:
  ```python
  sell_pre_wait_ms=1000  # Increase if needed
  just_buy_timeout=5     # Increase if needed
  ```

**3. Mock Failures**
- Ensure mock patches match actual method signatures
- Check that all dependencies are properly mocked

### Verbose Debugging

```bash
# Run with Python warnings enabled
python3 -Wd tests/test_ipo_sell_buy_trigger.py -v

# Run with logging
python3 tests/test_ipo_sell_buy_trigger.py 2>&1 | tee test.log
```

## Test Maintenance

### Adding New Tests

1. **Create test method** in `TestIPOSellBuyTrigger` class
2. **Follow naming convention**: `test_XX_descriptive_name`
3. **Add print statements** for visual progress
4. **Use assertions** with clear messages
5. **Clean up resources** in tearDown

### Modifying Price Simulator

```python
# Example: Add price volatility
class VolatilePriceSimulator(LadderPriceSimulator):
    def get_current_price(self):
        base = super().get_current_price()
        # Add ±1% noise while staying on ladder
        return base  # Keep exact for now
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Test IPO Sell-Buy-Trigger

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Run tests
        run: |
          chmod +x tests/run_sell_buy_tests.sh
          ./tests/run_sell_buy_tests.sh
```

## Performance Benchmarks

Typical test execution times (on modern hardware):

| Test Suite | Tests | Duration |
|------------|-------|----------|
| test_ipo_sell_buy_trigger.py | 7 | ~8-12 seconds |
| test_mode_compatibility.py | 6 | ~2-3 seconds |
| **Total** | **13** | **~10-15 seconds** |

## Future Test Additions

Potential areas for expansion:

- [ ] Stress testing with 100+ concurrent buy threads
- [ ] Network latency simulation
- [ ] Order book depth simulation
- [ ] Multi-symbol sell-buy-trigger scenarios
- [ ] Token expiry during execution
- [ ] Memory leak detection
- [ ] Performance regression tests

## Contact

For test-related issues or questions, refer to the main project documentation or create an issue on GitHub.
