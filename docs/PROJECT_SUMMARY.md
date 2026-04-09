# Complete Project Summary for AI Agent Handoff

## Project Overview
**TMS Automation** - A Python-based automated trading system for NEPSE (Nepal Stock Exchange) supporting both TMS and ATRAD platforms. Enables automated order placement with advanced features like IPO trigger modes, multi-queue monitoring, just-buy aggressive placement, and fade phases.

## System Architecture

### Core Components
1. **API Clients** (`api/`)
   - `TMSClient` - TMS platform API wrapper
   - `ATRADClient` - ATRAD platform API wrapper
   - Both support authentication, token refresh, order placement, and LTP fetching

2. **Order Services** (`services/`)
   - `BaseOrderService` - Abstract base class with shared logic
   - `OrderService` - TMS-specific implementation
   - `ATRADOrderService` - ATRAD-specific implementation
   - `MultiSymbolSequentialPriceFetcher` - Multi-symbol concurrent monitoring with round-robin client rotation

3. **Configuration** (`config/`)
   - `UserConfig` - TMS user configuration
   - `ATRADUserConfig` - ATRAD user configuration
   - Support for multi-user fetch clients

4. **Order Management** (`utils/`)
   - `OrderStore` - Loads, validates, and manages orders from JSON
   - `OrderScheduler` - Handles time-based order execution with token refresh

5. **Price Fetchers** (`services/`)
   - `TMSPriceFetcher` - Real-time LTP monitoring for TMS
   - `ATRADPriceFetcher` - Real-time LTP monitoring for ATRAD with market details

## Key Features

### 1. Order Execution Modes

#### Normal Mode
- Immediate order placement at specified price
- Supports both buy and sell orders

#### IPO Mode
- Ladder-based order placement
- Calculates price levels from base price to limit
- Places orders at each level as LTP rises
- Supports `skip_first`, `skip_second_last`, `double_buy`

#### IPO Trigger Mode
- Monitors LTP and triggers orders when thresholds reached
- **No-Ladder Mode**: Only places final order when second-last level reached
- **Ladder Mode**: Places orders at each calculated level
- **Dynamic Polling**: Switches between fast/slow polling based on switch threshold (3rd-last level)

#### Trigger Sell Mode
- **With Limit**: Calculates ladder levels from price down to limit, triggers at 2nd-last, places at limit+10%
- **Without Limit**: Legacy 2% trigger mode (triggers at price/1.02, places at price)

#### IPO Sell-Buy-Trigger Mode
Coordinated sell and buy order execution with precise timing when third-last ladder level is reached.

**User Roles**:
- **Seller**: Places sell order at second-last level (TMS or ATRAD)
- **Buyer**: Places buy orders at final level (TMS or ATRAD)
- **Fetch**: Monitors LTP for trigger detection (existing fetch users)

**Configuration**:
- `seller_config`: Path to seller user config
- `buyer_config`: Path to buyer user config
- `sell_quantity`: Quantity for sell order
- `sell_pre_wait_ms`: Wait time before sell sequence (default: 5000ms)
- `quantity`: Quantity for buy orders
- `price`: Base price for ladder calculation
- `limit`: Upper limit price

**Execution Flow**:
1. Calculate ladder (e.g., [100, 102, 104, 106, 108, 110])
2. Monitor LTP until third-last level reached (106)
3. Start `sell_pre_wait_ms` timer (default: 5000ms)
4. At timer-100ms (4900ms): Spawn buy threads at final price (110) using just-buy pattern
5. At timer expiry (5000ms): Place sell order at second-last price (108) with retry (3-5 attempts)
6. Exit when buy succeeds OR just_buy_timeout reached

**Threading Architecture**:
- Main thread monitors LTP and manages timer
- Buy spawner thread creates buy threads at intervals
- Sell thread places order with retry logic
- Uses threading.Event for success coordination

**Exit Conditions**:
- Buy order succeeds (200 response with code "0")
- OR just_buy_timeout reached (partial success if sell succeeded)

**Special Features**:
- Seller and buyer can be same or different users
- Supports TMS/ATRAD for both roles independently
- 1ms precision timing loop
- Thread-safe coordination with Event/Lock
- Clean resource cleanup in finally block
- **Scheduled execution support**: Works with `time` field for delayed execution
  - Uses dedicated `schedule_order_sell_buy()` method in [services/scheduler.py](../services/scheduler.py)
  - Handles two main clients (seller and buyer) for token refresh
  - Automatically refreshes tokens for seller, buyer, and fetch users (TMS or ATRAD)
  - Smart detection: Only TMS clients need token refresh, ATRAD clients are logged but skipped
  - Token refresh occurs 15 seconds before execution
  - Same countdown and logging pattern as other execution modes

### 2. Just Buy Mode
Aggressive multi-threaded order placement when switch threshold reached.

**Configuration**:
- `just_buy`: Enable/disable (default: false)
- `just_buy_interval_ms`: Interval between order attempts (default: 100ms)
- `just_buy_timeout`: Total duration in seconds (default: 5s)
- `just_buy_pre_wait_ms`: Wait time before starting (default: 0ms)
- `just_buy_max_requests`: Maximum attempts (default: None = use timeout)

**Behavior**:
- Spawns threads at configured interval
- Each thread attempts to place order
- First success stops all threads
- Falls back to normal trigger logic on failure

### 3. Fade Phase
Extended just-buy phase with slower interval after main phase fails.

**Configuration**:
- `just_buy_fade_interval_ms`: Slower interval for fade phase (default: None)
- `just_buy_fade_timeout`: Additional timeout in seconds (default: None)
- **Both required** for fade to activate

**Behavior**:
- Activates only if main just-buy phase fails
- Uses slower interval to avoid API overwhelming
- Extends total order placement duration
- Returns failure if fade also fails, falls back to normal trigger

**Recent Fix**: Fade parameters were missing from `execute_order()` function signatures and `order_params` dict in main.py. Now fully functional.

### 4. Multi-Queue Mode
Concurrent monitoring of multiple IPO symbols with automatic priority selection.

**Configuration**:
- `multi_queue`: Enable for orders (default: false)
- `queue_id`: Group orders with same queue_id
- All orders in group must have: `mode='ipo-trigger'`, `no_ladder=true`, matching `multi_queue` value

**Behavior**:
- Sequential symbol polling with round-robin client rotation
- First order to reach switch threshold becomes **priority order**
- Priority order executes immediately with `already_triggered=true` flag
- Remaining orders execute sequentially in order_store.json order
- If priority order just_buy fails → moves to next order (doesn't wait for trigger)

**Scheduled Time Support**:
- Uses time from first order in group
- Warns if orders have different times
- Integrates with OrderScheduler for time-based execution

### 5. Dynamic Polling Optimization
Reduces API load while maintaining responsiveness.

**States**:
- **Slow Polling**: When LTP < switch threshold (cooldown OFF)
- **Fast Polling**: When LTP >= switch threshold (cooldown ON, permanent)
- **Switch Threshold**: 3rd-last price level (or first level if <3 levels)

**Configuration**:
- `trigger_mode_poll_interval_ms`: Fast polling interval (default: 100ms)
- `trigger_mode_slow_poll_interval_ms`: Slow polling interval (default: 1000ms)
- `multi_fetch_poll_interval_ms`: Multi-queue polling interval (default: 100ms)

### 6. Queue System
Orders with `execute=true` are executed sequentially based on `queue_id` (ascending order).

**Multi-Queue Groups**:
- Orders with same `queue_id` and `multi_queue=true` execute as a group
- All others execute individually in queue order

## File Structure

### Configuration Files
- `stores/order_store.json` - Order definitions and instructions
- `stores/sell_store.json` - Sell order documentation
- `stores/ticker_store.json` - Ticker symbol mappings
- `config/*.json` - User configurations (TMS/ATRAD, main/fetch users)

### Core Implementation Files

#### Main Entry Point
- `main.py` - CLI interface, order execution orchestration, queue management

#### Services
- `services/base_order_service.py` - **Core logic** (1861 lines)
  - `_execute_ipo_trigger()` - Main IPO trigger orchestrator
  - `_execute_ladder_mode()` - Ladder-based order placement
  - `_execute_no_ladder_mode()` - No-ladder trigger logic
  - `_wait_for_no_ladder_trigger()` - Polling loop with dynamic optimization
  - `_execute_just_buy()` - Aggressive multi-threaded placement with fade phase
  - `_execute_trigger_sell()` - Sell trigger with ladder/legacy modes
  - `_execute_multi_queue_ipo_trigger()` - Multi-queue orchestration
  - `_execute_single_ipo_order()` - Single order execution helper
  - `_place_ladder_order()` - Individual ladder level placement
  - `_calculate_price_levels()` - Price ladder calculation

- `services/order_service.py` - TMS implementation
- `services/atrad_order_service.py` - ATRAD implementation
- `services/multi_symbol_price_fetcher.py` - Multi-queue symbol monitoring

#### Utilities
- `utils/order_store.py` - Order validation, normalization, multi-queue consistency checks
- `utils/order_scheduler.py` - Time-based scheduling with token refresh
- `utils/logger.py` - Logging configuration

## Parameter Flow Chain

### From Order Store to Execution

1. **Order Store JSON** → Contains all order parameters
2. **`order_store.py`** → Validates and normalizes parameters
3. **`main.py`** → Builds `order_params` dict from normalized order
4. **`execute_order()`** → Receives explicit parameters (TMS/ATRAD specific)
5. **`_execute_ipo_trigger()`** → Base class method receives all parameters
6. **`_execute_no_ladder_mode()`** → Packages just_buy params into dict
7. **`_wait_for_no_ladder_trigger()`** → Extracts and passes to just_buy
8. **`_execute_just_buy()`** → Executes main + fade phases

### Critical Parameters at Each Level

**Order Store** → All parameters with validation
**main.py order_params** → Must include ALL parameters (recently fixed to add fade params)
**execute_order()** → Must have explicit parameters in signature (recently fixed)
**_execute_ipo_trigger()** → Receives and forwards all parameters
**_execute_just_buy()** → Uses fade_interval_ms, fade_timeout for fade phase

## Recent Bug Fixes

### Issue: Fade Phase Not Working
**Root Cause**: Missing parameter passing at two levels
1. `execute_order()` signature missing: `just_buy_max_requests`, `just_buy_fade_interval_ms`, `just_buy_fade_timeout`
2. `main.py order_params` dict missing: `just_buy_pre_wait_ms`, `just_buy_max_requests`, `just_buy_fade_interval_ms`, `just_buy_fade_timeout`

**Why `**kwargs` Wasn't Enough**:
- Python spreads only keys present in dictionary
- If parameter not in dict, it's not passed even if function accepts `**kwargs`
- Need BOTH: explicit parameters in signature AND parameters in calling dict

**Files Fixed**:
- `services/order_service.py:59-61, 128-130`
- `services/atrad_order_service.py:51-53, 117-119`
- `main.py:777-781`

### Other Recent Work

1. **Multi-fetch polling interval** - Added `multi_fetch_poll_interval_ms` separate from trigger mode
2. **Just-buy max requests** - Added `just_buy_max_requests` for attempt-based control
3. **Multi-queue time support** - Multi-queue groups respect scheduled time from first order
4. **Sell limit support** - Ladder-based triggering when limit provided for sell orders
5. **Fade phase implementation** - Extended just-buy with slower interval after failure
6. **Multi-queue priority handling** - Correct behavior when priority order just_buy fails

## Git Status

**Current Branch**: `feat/multi-queue`
**Main Branch**: `main`

**Modified Files**:
- `main.py` - Added fade params to order_params dict
- `services/atrad_order_service.py` - Added fade params to execute_order()
- `services/base_order_service.py` - Core logic implementation
- `services/order_service.py` - Added fade params to execute_order()
- `stores/order_store.json` - Updated orders with fade configuration
- `utils/order_store.py` - Validation for all new parameters

**Recent Commits**:
- `87ffa0a` - update: multi queue to move directly into just buy and limit price for sell orders
- `5e18b41` - add: multi queue system
- `3dc6f96` - Merge pull request #10 from kayceem/feat/fetch-token-refresh
- `697de98` - remove: md files
- `40ab038` - update: refactor order service

## Current Order Configuration

**Active Orders** (from order_store.json):
1. **HFIN** (queue_id: 1, execute: true)
   - Price: 619.3, Limit: 619.3
   - Just buy: 200 requests @ 10ms
   - Fade: 60s @ 50ms

2. **RLEL** (queue_id: 3, execute: true)
   - Price: 707.1, Limit: 707.1
   - Just buy: 200 requests @ 50ms
   - Fade: 60s @ 50ms

3. **SKHEL** (queue_id: 5, execute: true)
   - Price: 669.7, Limit: 669.7
   - Just buy: 500 requests @ 100ms
   - Fade: 300s @ 100ms

## Important Design Patterns

### Template Method Pattern
`BaseOrderService` provides template methods, TMS/ATRAD override platform-specific methods like `_place_single_order()`, `_get_ltp()`.

### Strategy Pattern
Different execution modes (normal, IPO, trigger) implemented as separate methods with shared utilities.

### Thread Safety
`_execute_just_buy()` uses `threading.Event`, locks, and shared state for coordination.

### Client Rotation
`MultiSymbolSequentialPriceFetcher` rotates through fetch clients using round-robin index.

## Testing Checklist for Future Work

When modifying order execution:
1. ✅ Add parameters to order_store.json documentation
2. ✅ Add validation in utils/order_store.py
3. ✅ Add to execute_order() signature (both TMS & ATRAD)
4. ✅ Add to main.py order_params dict
5. ✅ Pass through _execute_ipo_trigger() if needed
6. ✅ Implement logic in appropriate base method
7. ✅ Test with actual order execution
8. ✅ Verify parameter flow end-to-end

## Key Takeaways for Next Agent

1. **Parameter passing requires explicit handling** - Cannot rely on `**kwargs` alone
2. **Multi-queue is complex** - Involves sequential polling, priority detection, already_triggered flag
3. **Just-buy and fade are separate phases** - Main phase uses interval/timeout or max_requests, fade extends with slower interval
4. **BaseOrderService is the core** - Most logic lives here, platform services are thin wrappers
5. **Order validation is strict** - Multi-level validation from order_store through execution
6. **Thread safety matters** - Just-buy spawns multiple threads, needs proper coordination
7. **Dynamic polling optimization** - Reduces API load but adds complexity to state management

## Contact Points for Debugging

- LTP fetching issues → Check price fetchers and client rotation
- Order placement failures → Check platform-specific `_place_single_order()`
- Trigger logic issues → Check `_wait_for_no_ladder_trigger()` and switch threshold calculation
- Multi-queue issues → Check `MultiSymbolSequentialPriceFetcher` and priority detection
- Parameter not working → Trace through entire parameter flow chain (all 8 levels)
- Fade not activating → Verify both fade params are set AND main just-buy failed
