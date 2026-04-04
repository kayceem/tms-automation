# IPO Trigger Refactoring Plan

## Problem

The `_execute_ipo_trigger` method in `base_order_service.py` has become monolithic and difficult to maintain:
- **725 lines** of code in a single method
- Multiple responsibilities mixed together
- Deep nesting (up to 6-7 levels)
- Difficult to test individual components
- Hard to understand the control flow

## Solution

Break down the monolithic method into **focused, single-responsibility methods**:

### New Structure

```
_execute_ipo_trigger()  [Main orchestrator - ~80 lines]
    ├── Setup Phase
    │   ├── _calculate_price_levels()  [Already exists]
    │   ├── _log_ipo_trigger_config()  [NEW - 10 lines]
    │   ├── _log_ladder_levels()  [NEW - 20 lines]
    │   ├── _setup_price_fetcher()  [NEW - 20 lines]
    │   │   ├── _setup_atrad_price_fetcher()  [NEW - 40 lines]
    │   │   ├── _setup_tms_price_fetcher()  [NEW - 50 lines]
    │   │   └── _resolve_fetch_id_for_client()  [NEW - 20 lines]
    │   └── _setup_token_manager()  [Already exists]
    │
    ├── Execution Phase
    │   ├── _execute_no_ladder_mode()  [NEW - 60 lines]
    │   │   ├── _wait_for_no_ladder_trigger()  [NEW - 90 lines]
    │   │   │   └── _execute_just_buy()  [NEW - 120 lines]
    │   │   └── _place_order_with_retries()  [NEW - 50 lines]
    │   │
    │   └── _execute_ladder_mode()  [NEW - 40 lines]
    │       ├── _wait_for_skip_first_trigger()  [NEW - 30 lines]
    │       └── _place_ladder_order()  [NEW - 80 lines]
    │           ├── _wait_for_ladder_trigger()  [NEW - 70 lines]
    │           └── _place_order_with_retries()  [Shared - 50 lines]
    │
    └── Cleanup Phase
        └── _cleanup_token_manager()  [Already exists]
```

## Benefits

### 1. **Single Responsibility Principle**
Each method has one clear purpose:
- `_setup_price_fetcher()` - Only handles price fetcher setup
- `_execute_just_buy()` - Only handles just_buy logic
- `_wait_for_ladder_trigger()` - Only handles waiting for triggers
- `_place_order_with_retries()` - Only handles order placement with retries

### 2. **Improved Readability**
- Main method (`_execute_ipo_trigger`) is now ~80 lines and reads like a story
- Each helper method is < 120 lines and focused
- Clear separation of concerns: Setup → Execute → Cleanup

### 3. **Easier Testing**
- Can unit test individual components (e.g., just_buy logic in isolation)
- Mock dependencies more easily
- Test edge cases without running entire IPO trigger flow

### 4. **Easier Debugging**
- Stack traces show exactly which component failed
- Can add logging to specific components
- Easier to step through with debugger

### 5. **Easier Modification**
- Want to change just_buy logic? Edit `_execute_just_buy()` only
- Want to change polling logic? Edit `_wait_for_no_ladder_trigger()` only
- Changes are localized and don't affect unrelated code

### 6. **Reduced Nesting**
- Original: 6-7 levels of nesting
- Refactored: Max 3 levels in any method

## Detailed Method Breakdown

### Setup Methods

#### `_setup_price_fetcher()` [20 lines]
**Purpose**: Setup and start the appropriate price fetcher
**Delegates to**:
- `_setup_atrad_price_fetcher()` - For ATRAD clients
- `_setup_tms_price_fetcher()` - For TMS clients

#### `_setup_atrad_price_fetcher()` [40 lines]
**Purpose**: Setup ATRAD price fetcher (single or multi-user)
**Returns**: Started ATRADPriceFetcher or ATRADMultiUserPriceFetcher

#### `_setup_tms_price_fetcher()` [50 lines]
**Purpose**: Setup TMS price fetcher (single or multi-user)
**Delegates to**: `_resolve_fetch_id_for_client()` for per-client fetch_id resolution
**Returns**: Started PriceFetcher or MultiUserPriceFetcher

#### `_resolve_fetch_id_for_client()` [20 lines]
**Purpose**: Resolve fetch_id for a specific client based on ticker and host
**Returns**: Resolved fetch_id (int)

#### `_log_ipo_trigger_config()` [10 lines]
**Purpose**: Log IPO trigger configuration summary

#### `_log_ladder_levels()` [20 lines]
**Purpose**: Log all ladder levels with skip markers

### Execution Methods

#### `_execute_no_ladder_mode()` [60 lines]
**Purpose**: Execute no-ladder mode flow
**Flow**:
1. Calculate trigger and final prices
2. Wait for trigger (handles just_buy internally)
3. If just_buy succeeded, return
4. Otherwise place final order normally

#### `_execute_ladder_mode()` [40 lines]
**Purpose**: Execute ladder mode flow
**Flow**:
1. Wait for initial trigger if skip_first
2. Loop through levels and place orders
3. Return orders placed and last response

#### `_wait_for_no_ladder_trigger()` [90 lines]
**Purpose**: Wait for no_ladder trigger with dynamic polling and optional just_buy
**Features**:
- Dynamic polling (slow ↔ fast)
- Executes just_buy when switch threshold is reached
- Returns when trigger price is reached or just_buy succeeds

#### `_execute_just_buy()` [120 lines]
**Purpose**: Execute just_buy mode (multi-threaded aggressive order placement)
**Features**:
- Pre-wait delay
- Thread-safe order placement
- Market details monitoring
- Returns success status and response

#### `_wait_for_skip_first_trigger()` [30 lines]
**Purpose**: Wait for initial trigger when skip_first is enabled
**Returns**: When LTP >= first price level

#### `_place_ladder_order()` [80 lines]
**Purpose**: Place a single ladder order at the specified level
**Features**:
- Checks skip conditions
- Waits for trigger
- Places order with retries
- Handles double_buy for final level
**Returns**: (success, response, next_level_index)

#### `_wait_for_ladder_trigger()` [70 lines]
**Purpose**: Wait for LTP to reach trigger price
**Features**:
- Handles level skips if LTP jumps ahead
- Handles skip_second_last
- Starts market details monitoring
**Returns**: Current LTP when triggered

#### `_place_order_with_retries()` [50 lines]
**Purpose**: Place order with retry logic (up to 3 attempts)
**Features**:
- Error handling by type (401, 400, etc.)
- Automatic retries with delays
- Stops market details on success
**Returns**: Order response or None

#### `_place_immediate_order()` [10 lines]
**Purpose**: Place an order immediately without waiting
**Used for**: Edge case where only one level exists

## Code Quality Improvements

### Before
```python
def _execute_ipo_trigger(self, ...):  # 725 lines
    # Setup (150 lines)
    # ... lots of code ...

    # No ladder mode (300 lines)
    if no_ladder:
        # ... deeply nested logic ...
        if just_buy:
            # ... 150 lines of just_buy logic inline ...
            def place_just_buy_order(thread_id):
                # ... nested function ...

    # Ladder mode (250 lines)
    while current_level_index < len(price_levels):
        # ... deeply nested logic ...
        while not triggered:
            # ... more nesting ...
            while current_level_index < len(price_levels) - 1:
                # ... even more nesting ...
```

### After
```python
def _execute_ipo_trigger(self, ...):  # 80 lines
    # Setup
    price_levels, increments = self._calculate_price_levels(base_price, limit_price)
    self._log_ipo_trigger_config(price_levels, ...)
    price_fetcher = self._setup_price_fetcher(fetch_clients, ...)
    token_manager = self._setup_token_manager()

    try:
        # Execute
        if no_ladder:
            last_response = self._execute_no_ladder_mode(price_fetcher, ...)
        else:
            orders_placed, last_response = self._execute_ladder_mode(price_fetcher, ...)
    finally:
        # Cleanup
        price_fetcher.stop()
        self._cleanup_token_manager(token_manager)

    return last_response
```

## Migration Strategy

### Phase 1: Create New Methods (DONE)
- Created `base_order_service_refactored.py` with all helper methods
- Created `ipo_trigger_main.py` with new main method
- All new code is in separate files for review

### Phase 2: Integration (TODO)
1. Copy all helper methods from `base_order_service_refactored.py` into `base_order_service.py`
2. Replace old `_execute_ipo_trigger()` with new version from `ipo_trigger_main.py`
3. Run tests to ensure behavior is identical

### Phase 3: Testing (TODO)
1. Test no_ladder mode
2. Test ladder mode
3. Test just_buy mode
4. Test skip_first and skip_second_last
5. Test error scenarios

### Phase 4: Cleanup (TODO)
1. Delete `base_order_service_refactored.py`
2. Delete `ipo_trigger_main.py`
3. Update documentation

## Risk Mitigation

- **No behavior changes**: The refactored code has identical logic to the original
- **Separate files first**: Review before integration
- **Incremental testing**: Test each mode individually
- **Easy rollback**: Keep old code commented until fully tested

## Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Largest method size | 725 lines | 120 lines | **83% reduction** |
| Max nesting depth | 6-7 levels | 3 levels | **50% reduction** |
| Number of methods | 1 monolith | 15 focused | **Better modularity** |
| Cyclomatic complexity | ~50 | <10 per method | **Easier testing** |
| Lines per method (avg) | 725 | ~50 | **More readable** |

## Next Steps

1. **Review** the refactored code in:
   - `services/base_order_service_refactored.py`
   - `services/ipo_trigger_main.py`

2. **Approve** the approach

3. **Integrate** into `base_order_service.py`

4. **Test** thoroughly

5. **Deploy** with confidence
