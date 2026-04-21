# Plan: Parallel Cycle-Users Fetcher

## Summary
Implement an opt-in parallel cycle-users scheduler for both multi-user fetchers:
- `MultiUserPriceFetcher` for TMS
- `ATRADMultiUserPriceFetcher` for ATRAD

Keep current sequential rotation as the default. The new behavior is specifically for trigger-mode multi-user price polling and should preserve the current slow/fast trigger workflow:
- slow phase stays sequential
- fast phase switches the same fetcher instance to parallel cycle-users mode

Parallel mode should follow the `utils/atrad_latency_tester.py` experiment:
- response-driven cycling
- configurable spawn interval
- no hard global wait by default
- separate oldest-user fallback timeout
- optional strict wait to enforce a minimum global gap between dispatches

Decisions locked:
- implement for both TMS and ATRAD fetchers
- sequential remains the default runtime behavior
- `requests_per_user` remains sequential-only
- no separate slow parallel scheduler in v1
- no fetcher replacement mid-workflow; use one fetcher instance that can switch scheduler mode live

## Implementation Changes

### 1. Fetcher scheduler model
Extend both multi-user fetchers to support two internal scheduler modes:
- `sequential`
- `parallel`

Sequential mode:
- preserve existing behavior
- keep `requests_per_user`
- keep existing cooldown behavior
- keep current request path and polling rhythm

Parallel mode:
- ignore `requests_per_user`
- maintain a pooled scheduler across all fetch users
- seed initial requests across users when the fetcher starts or when it switches into parallel mode
- when a response completes, immediately schedule the next request for that same user if the fetcher is still active
- if no response completes within `parallel_cycle_timeout_ms`, dispatch the user with the oldest last-dispatch time
- if `parallel_wait` is enabled, enforce a strict global minimum gap of `parallel_spawn_interval_ms` between dispatches
- if `parallel_wait` is disabled, allow response-driven dispatches to occur closer than `parallel_spawn_interval_ms`

Implementation rules:
- do not replace the fetcher object during runtime
- do not restart trigger workflows when mode changes
- keep `start()`, `stop()`, `pause()`, `resume()`, `get_latest_ltp()`, and `update_poll_settings(...)` available
- add a scheduler-mode update path, for example `update_scheduler_settings(...)` or equivalent, so workflows can switch from slow sequential to fast parallel without recreating the fetcher

### 2. Slow-to-fast trigger behavior
Preserve the current no-ladder trigger intent:
- below switch threshold:
  - use slow polling
  - keep scheduler mode sequential
  - keep cooldown disabled
- once switch threshold is reached:
  - if `just_buy` runs, keep current just-buy flow unchanged
  - otherwise switch the same fetcher instance into fast parallel mode

Concretely:
- `trigger_mode_slow_poll_interval_ms` continues to control the slow phase
- `trigger_mode_poll_interval_ms` continues to represent the fast trigger-side polling regime
- when parallel fetching is enabled, the fast phase uses:
  - scheduler mode = `parallel`
  - `parallel_spawn_interval_ms`
  - `parallel_cycle_timeout_ms`
  - `parallel_wait`

Do not add `slow_spawn_interval_ms` or a separate slow parallel scheduler in v1.

### 3. Config additions
Add new persisted config fields to both `UserConfig` and `ATRADUserConfig`:
- `trigger_mode_parallel_fetch_enabled: bool = True`
- `trigger_mode_parallel_spawn_interval_ms: int`
- `trigger_mode_parallel_cycle_timeout_ms: int`
- `trigger_mode_parallel_wait: bool = False`

Config behavior:
- include these keys in inherited defaults so `users/default.json` can control them
- include them in `to_dict()` / `from_dict()` persistence
- pass them from order-service setup into both multi-user fetcher constructors
- do not remove or repurpose `trigger_mode_requests_per_fetch_user`

### 4. Order-service integration
Update the multi-user fetcher setup path in `BaseOrderService` so both fetchers receive:
- sequential settings
- parallel settings
- default scheduler mode

The service should still instantiate:
- single-user fetchers for single fetch clients
- multi-user fetchers for multiple fetch clients

No workflow outside the fetcher boundary should need to know how threads are scheduled internally. The workflow layer should only:
- update poll interval
- enable/disable cooldown
- switch scheduler mode when the threshold is crossed

### 5. ATRAD market-details interaction
`ATRADMultiUserPriceFetcher` already supports market-details mode. The parallel scheduler must integrate cleanly with it:
- starting market details must stop or pause parallel LTP dispatching before market-detail requests begin
- stopping market details must restore normal LTP fetching in the previously configured scheduler mode
- no leftover worker threads should continue updating LTP while market-details mode is active

### 6. Concurrency and safety rules
Parallel fetching should overlap requests across users, but the implementation must remain predictable:
- no new dispatches after `stop()`
- `pause()` blocks new dispatches but does not require killing in-flight requests
- in-flight requests may finish naturally after pause/stop, but should not schedule follow-up work once the fetcher is no longer active
- only successful fetches update `_latest_ltp`
- failures must be logged and the affected user remains eligible for future dispatch
- latest-value writes and scheduler state changes remain thread-safe

## Public Interfaces / Additions
- New config fields in both TMS and ATRAD user configs:
  - `trigger_mode_parallel_fetch_enabled`
  - `trigger_mode_parallel_spawn_interval_ms`
  - `trigger_mode_parallel_cycle_timeout_ms`
  - `trigger_mode_parallel_wait`
- Multi-user fetchers gain a runtime scheduler update capability so workflows can switch from slow sequential to fast parallel on the same instance

No CLI or order-store schema change is required for v1.

## Test Plan

### Fetcher tests
Add focused unit tests for both multi-user fetchers covering:
- sequential mode remains unchanged and honors `requests_per_user`
- parallel mode ignores `requests_per_user`
- initial seed dispatch covers users in cycle order
- response-driven cycling dispatches the next request for the responding user
- no-response fallback dispatch selects the oldest user after `parallel_cycle_timeout_ms`
- strict-wait mode blocks dispatches that would violate the global minimum interval
- `pause()` prevents new dispatches
- `resume()` restarts dispatching
- `stop()` prevents further dispatches and joins scheduler threads cleanly
- only successful fetches update `_latest_ltp`

### Trigger-workflow tests
Add tests around no-ladder trigger behavior to verify:
- slow phase uses sequential mode
- crossing the switch threshold flips the same fetcher instance to parallel mode
- just-buy path still works with the new fetcher API
- fast polling still disables/enables cooldown as expected

### ATRAD-specific tests
Add tests verifying:
- market-details start pauses or stops parallel LTP scheduling correctly
- market-details stop restores normal LTP scheduling
- no LTP updates leak through while market-details mode is active

### Config and setup tests
Add tests verifying:
- new config fields load and persist for both user-config types
- inherited defaults apply correctly from `users/default.json`
- `BaseOrderService` passes the new parallel settings into both multi-user fetcher constructors

### Regression checks
- existing `pytest` suite continues to pass
- single-user fetchers remain unchanged
- multi-user sequential behavior remains unchanged when parallel is disabled

## Assumptions and Defaults
- Sequential rotation remains the default behavior for all existing users unless `trigger_mode_parallel_fetch_enabled=true`
- Parallel cycle-users is only introduced for multi-user fetchers, not single-user fetchers
- `parallel_spawn_interval_ms` is a normal stagger target unless `parallel_wait=true`
- `parallel_cycle_timeout_ms` is a separate fallback timeout for no-wait mode
- Fast trigger mode switches from sequential to parallel in-place on the same fetcher instance
- Slow mode remains sequential in v1
