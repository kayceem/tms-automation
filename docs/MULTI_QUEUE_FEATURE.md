# Multi-Queue IPO Trigger Feature

## Overview

The multi-queue feature allows multiple IPO trigger orders with the same `queue_id` to monitor their symbols concurrently. The first order to reach its switch threshold becomes the priority order and is executed first, followed by the remaining orders sequentially.

## Use Case

**Scenario**: You have multiple IPO opportunities but can only execute one at a time due to fund limitations. You want to automatically execute whichever IPO reaches its trigger price first.

**Example**:
- IPO A (BJHL) - expecting to trigger around 10:15 AM
- IPO B (NLIC) - expecting to trigger around 10:30 AM

With multi-queue, both are monitored simultaneously. If NLIC triggers first (unexpected), it executes immediately. Then BJHL executes afterward.

## How It Works

### 1. Sequential Symbol Monitoring

A single `MultiSymbolSequentialPriceFetcher` polls each symbol one after another:

```
Poll BJHL → Check threshold → Poll NLIC → Check threshold → Repeat
```

- Uses `poll_interval_ms` between each symbol fetch
- First symbol to reach switch threshold becomes priority

### 2. Priority Selection

**Switch Threshold**: The 3rd-last ladder level (e.g., if ladder has 6 levels, threshold is level 3)

When any order's LTP >= switch_threshold:
1. That order becomes **PRIORITY**
2. Monitoring stops for other orders
3. Priority order executes completely (with just_buy if enabled)
4. Remaining orders execute sequentially

### 3. Execution Flow

```
Queue 2: [BJHL, NLIC] (both multi_queue=true, no_ladder=true)

Step 1: Start sequential monitoring
  ├─ Fetch BJHL LTP → 640 (threshold: 700) ❌
  ├─ Fetch NLIC LTP → 1100 (threshold: 1200) ❌
  ├─ Fetch BJHL LTP → 680 (threshold: 700) ❌
  ├─ Fetch NLIC LTP → 1210 (threshold: 1200) ✓ TRIGGERED!
  └─ NLIC becomes PRIORITY

Step 2: Execute NLIC (priority order)
  ├─ Just buy if enabled
  ├─ Place final order
  └─ Mark as successful

Step 3: Execute BJHL (remaining order)
  ├─ Normal IPO trigger flow
  └─ Mark as successful

Complete!
```

## Configuration

### Requirements

All multi-queue orders must have:
- ✅ `multi_queue: true`
- ✅ `no_ladder: true`
- ✅ `mode: "ipo-trigger"`
- ✅ Same `queue_id` value
- ✅ Same `fetch_clients` (validated)

### Validation Rules

1. **Consistent multi_queue**: All orders with same `queue_id` must have matching `multi_queue` value
2. **Minimum 2 orders**: Multi-queue requires at least 2 orders (warns if only 1)
3. **no_ladder required**: `multi_queue=true` requires `no_ladder=true`
4. **ipo-trigger required**: `multi_queue=true` requires `mode='ipo-trigger'`

### Example order_store.json

```json
{
  "orders": [
    {
      "id": "bjhl_ipo",
      "execute": true,
      "queue_id": 2,
      "ticker": "BJHL",
      "mode": "ipo-trigger",
      "quantity": 625,
      "price": 640.0,
      "limit": 700.0,
      "no_ladder": true,
      "multi_queue": true,
      "just_buy": true,
      "just_buy_pre_wait_ms": 500,
      "just_buy_interval_ms": 5,
      "just_buy_timeout": 10
    },
    {
      "id": "nlic_ipo",
      "execute": true,
      "queue_id": 2,
      "ticker": "NLIC",
      "mode": "ipo-trigger",
      "quantity": 500,
      "price": 1200.0,
      "limit": 1320.0,
      "no_ladder": true,
      "multi_queue": true,
      "just_buy": true,
      "just_buy_pre_wait_ms": 500,
      "just_buy_interval_ms": 5,
      "just_buy_timeout": 10
    }
  ]
}
```

## Edge Cases

### 1. Already Triggered When Starting

If an order's LTP is already >= switch_threshold when monitoring starts:
- First poll detects it immediately
- Becomes priority order right away
- Other orders stop monitoring

### 2. Simultaneous Trigger (Unlikely)

If multiple orders reach threshold in the same polling iteration:
- Alphabetically first ticker becomes priority (tiebreaker)
- Example: BJHL vs NLIC → BJHL wins

### 3. Single Order in Multi-Queue

If only 1 order has `multi_queue=true` in a queue_id:
- Warning logged
- Executes normally (no concurrent monitoring needed)

### 4. Mixed multi_queue in Same Queue

**Invalid Configuration**:
```json
{"queue_id": 2, "multi_queue": true},   // BJHL
{"queue_id": 2, "multi_queue": false}   // NLIC
```

**Error**: "Orders in queue 2 have inconsistent multi_queue values"

## Implementation Details

### New Components

#### 1. MultiSymbolSequentialPriceFetcher
**File**: `services/multi_symbol_price_fetcher.py`

**Purpose**: Monitor multiple symbols sequentially and detect priority

**Key Methods**:
- `start()` - Begin monitoring loop
- `get_latest_ltp(symbol)` - Get LTP for specific symbol
- `get_priority_symbol()` - Returns which symbol reached threshold first
- `stop()` - Stop monitoring

**Monitoring Loop**:
```python
while running:
    for config in symbols_config:
        ltp = fetch_ltp_for_symbol(config)

        if ltp >= config.switch_threshold:
            priority_symbol = config.symbol
            stop_monitoring()
            break

        sleep(poll_interval_ms)
```

#### 2. BaseOrderService._execute_multi_queue_ipo_trigger()
**File**: `services/base_order_service.py`

**Purpose**: Orchestrate multi-queue execution

**Flow**:
1. Build symbol configs with switch thresholds
2. Create MultiSymbolSequentialPriceFetcher
3. Start monitoring
4. Wait for priority symbol
5. Execute priority order
6. Execute remaining orders sequentially

#### 3. main.execute_multi_queue_group()
**File**: `main.py`

**Purpose**: Handle multi-queue execution from order store

**Flow**:
1. Resolve all tickers to security IDs
2. Create order service and fetch clients
3. Call `_execute_multi_queue_ipo_trigger()`
4. Mark all orders as successful

### Modified Components

#### 1. order_store.py
**Changes**:
- Added `multi_queue` validation
- Added `_validate_multi_queue_consistency()` method
- Validates all orders in same queue_id have matching multi_queue

#### 2. main.py
**Changes**:
- Group orders by `queue_id`
- Detect multi_queue groups
- Call `execute_multi_queue_group()` for multi-queue
- Normal sequential execution for non-multi-queue

## Logging

### Multi-Queue Monitoring
```
[user] Multi-symbol fetcher initialized: 2 symbols, interval=3ms
[user] Multi-queue order: bjhl_ipo (BJHL) switch_threshold=Rs. 700.0
[user] Multi-queue order: nlic_ipo (NLIC) switch_threshold=Rs. 1200.0
[user] Multi-symbol fetcher started
[user] Waiting for first order to reach switch threshold...
[user] Multi-queue monitoring: BJHL=680.0, NLIC=1150.0
[user] Multi-queue monitoring: BJHL=695.0, NLIC=1210.0
[user] Multi-queue: NLIC reached switch threshold (1200.0) - LTP=1210.0 - Setting as PRIORITY order
[user] Multi-symbol fetcher stopped
[user] Multi-queue final LTPs: BJHL=695.0, NLIC=1210.0
[user] PRIORITY ORDER: nlic_ipo (NLIC)
```

### Order Execution
```
[user] Executing priority order: nlic_ipo
[user] NO LADDER MODE: Waiting for LTP >= Rs. 1320.0 to place FINAL order at Rs. 1452.0
[user] JUST BUY ACTIVATED: Starting aggressive order placement...
[user] Just Buy SUCCEEDED! Placed 158 orders, at least one succeeded
[user] IPO TRIGGER COMPLETE: 1 orders placed

[user] Executing remaining order: bjhl_ipo (BJHL)
[user] NO LADDER MODE: Waiting for LTP >= Rs. 700.0 to place FINAL order at Rs. 770.0
...
[user] MULTI-QUEUE COMPLETE: 2 orders executed
```

## Performance Considerations

### Polling Speed

**Sequential polling time**:
```
Total cycle time = num_symbols × poll_interval_ms
Example: 2 symbols × 3ms = 6ms per complete cycle
```

**Recommendation**: Use fast `poll_interval_ms` (3-5ms) for quick detection

### Just Buy Compatibility

Multi-queue works seamlessly with just_buy:
- Monitor until switch threshold
- Execute just_buy for priority order
- If just_buy fails, fall back to normal trigger
- Then execute remaining orders

## Queue Execution Examples

### Example 1: Simple Multi-Queue
```json
Queue 1: [Order A] (multi_queue=false)
Queue 2: [Order B, Order C] (multi_queue=true)
Queue 3: [Order D] (multi_queue=false)
```

**Execution**:
1. Execute Order A (queue 1)
2. Monitor B and C concurrently (queue 2)
   - Whichever triggers first executes
   - Then the other executes
3. Execute Order D (queue 3)

### Example 2: Mixed Queue IDs
```json
Queue 1: [A, B] (multi_queue=true)
Queue 2: [C] (multi_queue=false)
Queue 2: [D] (multi_queue=false)
Queue 3: [E, F, G] (multi_queue=true)
```

**Execution**:
1. Monitor A and B (queue 1) → Execute priority → Execute remaining
2. Execute C (queue 2)
3. Execute D (queue 2)
4. Monitor E, F, and G (queue 3) → Execute priority → Execute remaining 2

## Testing Checklist

- [ ] Two orders, both reach threshold (normal case)
- [ ] Two orders, one already triggered when starting
- [ ] Three+ orders in multi-queue group
- [ ] Multi-queue with just_buy enabled
- [ ] Multi-queue with just_buy disabled
- [ ] Inconsistent multi_queue values (should error)
- [ ] Multi-queue without no_ladder (should error)
- [ ] Multi-queue without ipo-trigger mode (should error)
- [ ] Single order with multi_queue=true (should warn)
- [ ] Mixed TMS and ATRAD orders (not supported, should error if same queue)
- [ ] Priority order fails (should still execute remaining)

## Files Modified

1. ✅ `services/multi_symbol_price_fetcher.py` - NEW
2. ✅ `services/base_order_service.py` - Added `_execute_multi_queue_ipo_trigger()` and `_execute_single_ipo_order()`
3. ✅ `utils/order_store.py` - Added validation and `_validate_multi_queue_consistency()`
4. ✅ `main.py` - Added `execute_multi_queue_group()` and queue grouping logic
5. ✅ `stores/order_store.json` - Added documentation and examples

## Summary

The multi-queue feature provides intelligent concurrent monitoring of multiple IPO triggers, automatically prioritizing whichever opportunity triggers first. It's perfect for scenarios where you want to capture the best opportunity among multiple possibilities without manual intervention.

**Key Benefits**:
- ✅ Automatic priority selection
- ✅ No missed opportunities
- ✅ Works with just_buy
- ✅ Sequential polling (no concurrent API calls)
- ✅ Clean integration with existing queue system
