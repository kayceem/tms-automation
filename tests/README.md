# IPO Trigger Mode Test Suite

Comprehensive test suite for validating IPO Trigger functionality in a simulated environment without hitting the live market.

## Overview

This test suite simulates the complete IPO trigger workflow including:

- ✅ **Price fetching** with 200ms delays (realistic GET request simulation)
- ✅ **Order placement** with 1s delays (realistic POST request simulation)
- ✅ **Token refresh** simulation
- ✅ **Skip first** ladder level functionality
- ✅ **Skip second-last** ladder level functionality
- ✅ **Multi-level price jumps** (edge case handling)
- ✅ **Retry logic** with max 3 attempts per level
- ✅ **Base quantity** vs final quantity validation
- ✅ **Market price simulation** (+2% increments from base to limit+10%)

## Features

### Fake Market Simulator
- Simulates realistic price movements for IPO stocks
- Starts at base price, advances in +2% increments
- Ends at limit price + 10%
- Thread-safe price updates
- Configurable price jumps for testing edge cases

### Fake TMS Client
- Simulates API calls with realistic delays:
  - **GET requests (LTP fetch)**: 200ms delay
  - **POST requests (order placement)**: 1s delay
- Tracks all orders placed
- Supports failure simulation for retry testing
- Records token refresh calls

### Test Coverage

1. **Basic Trigger (No Skips)**
   - Tests normal ladder execution
   - Validates all levels are executed in order
   - Confirms base_quantity vs final quantity logic

2. **Skip First Level**
   - Validates skip_first flag
   - Ensures first ladder level is skipped
   - Verifies trigger starts from second level

3. **Skip Second-Last Level**
   - Validates skip_second_last flag
   - Ensures second-to-last level is skipped
   - Jumps directly to final limit order

4. **Skip Both (First + Second-Last)**
   - Tests combination of both skip flags
   - Validates correct execution with multiple skips

5. **Price Jump (Multiple Levels)**
   - Tests edge case: LTP jumps past several levels
   - Validates that missed levels are skipped
   - Ensures next order is placed at correct level

6. **Retry Logic (Max 3 Attempts)**
   - Tests retry mechanism
   - Validates max 3 attempts before auto-skip
   - Confirms orders eventually succeed after retries

7. **Base Quantity vs Final Quantity**
   - Validates base_quantity for levels 1 through n-1
   - Validates order_quantity for final level (n)
   - Confirms correct quantities for each order

## Running the Tests

### Prerequisites

```bash
# Ensure you're in the project root directory
cd /home/kayc/Code/Stock/tms-automation
```

### Run All Tests

```bash
python3 tests/test_ipo_trigger.py
```

### Expected Output

```
IPO Trigger Mode - Comprehensive Test Suite
======================================================================
TEST: Basic Trigger (No Skips)
======================================================================
Testing basic trigger mode with all ladder levels...
  [MARKET] Price advanced to Rs. 102.0 (Level 2/7)
    [user1] Order placed: Rs. 100.0 x 10 (Order #1)
  [MARKET] Price advanced to Rs. 104.0 (Level 3/7)
    [user1] Order placed: Rs. 102.0 x 10 (Order #2)
...

✓ PASSED in 15.34s

======================================================================
TEST SUMMARY
======================================================================
Tests Passed: 7
Tests Failed: 0
Total Tests:  7
Success Rate: 100.0%
======================================================================
```

## Test Configuration

### Timing Parameters

The tests use accelerated timing for faster execution:

```python
trigger_mode_poll_interval_ms=50    # 50ms polling (vs 100ms in production)
trigger_mode_refresh_interval_seconds=10  # 10s refresh (vs 60s in production)
```

### Market Simulation

- **Base Price**: 100.0
- **Limit Price**: 110.0
- **Target Price** (Limit +10%): 121.0
- **Price Ladder**: 100.0 → 102.0 → 104.0 → 106.1 → 108.1 → 110.2 → 121.0

### Delays

- **GET Request (LTP fetch)**: 200ms
- **POST Request (Order placement)**: 1000ms (1 second)
- **Price advancement**: 3-4 seconds between levels

## Test Architecture

```
tests/test_ipo_trigger.py
├── FakeMarketSimulator       # Simulates price movements
│   ├── get_current_price()   # Returns LTP with 200ms delay
│   ├── advance_price()       # Move to next price level
│   └── jump_to_level()       # Jump to specific level
│
├── FakeTMSClient            # Simulates TMS API
│   ├── get_ltp()            # Fetch LTP (200ms delay)
│   ├── place_order()        # Place order (1s delay)
│   └── refresh_tokens()     # Token refresh simulation
│
└── TestIPOTrigger           # Test suite runner
    ├── test_basic_trigger_no_skips()
    ├── test_skip_first_level()
    ├── test_skip_second_last_level()
    ├── test_skip_both_first_and_second_last()
    ├── test_price_jump_multiple_levels()
    ├── test_retry_logic_max_3_attempts()
    └── test_base_quantity_vs_final_quantity()
```

## Adding New Tests

To add a new test:

```python
def test_your_new_test(self):
    """Test description."""
    print("Testing your feature...")

    # Setup
    market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
    user_config = self.create_user_config('user1')
    fake_client = FakeTMSClient(user_config, market)

    # ... test implementation ...

    # Assertions
    assert some_condition, "Error message"
```

Then register it in `main()`:

```python
suite.run_test("Your Test Name", suite.test_your_new_test)
```

## Troubleshooting

### Test Timeouts

If tests timeout, check:
- Price advancement thread is running
- Delays are appropriate for test duration
- Market simulator is advancing prices

### Order Count Mismatches

If order counts don't match expectations:
- Check skip flags (skip_first, skip_second_last)
- Verify price advancement timing
- Review retry logic (failed orders)

### Import Errors

Ensure you're running from project root:
```bash
cd /home/kayc/Code/Stock/tms-automation
python3 tests/test_ipo_trigger.py
```

## Success Criteria

✅ All 7 tests pass
✅ No exceptions or errors
✅ Correct order quantities (base_quantity vs final)
✅ Skip flags work as expected
✅ Edge cases handled properly
✅ Retry logic functions correctly

## Future Enhancements

Potential additions to test suite:

- [ ] Multi-user parallel execution tests
- [ ] Queue execution tests (multiple orders)
- [ ] Token expiry and refresh scenarios
- [ ] Network failure simulations
- [ ] Concurrent price fetching tests
- [ ] Memory leak detection
- [ ] Performance benchmarking

## Notes

- Tests run in **isolated environment** - no real orders placed
- Market simulation is **deterministic** for reproducible results
- All timing is **accelerated** for faster test execution
- Tests validate **core IPO trigger logic** without external dependencies
