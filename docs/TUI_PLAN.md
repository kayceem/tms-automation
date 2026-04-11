# Plan: Add a Modular Textual TUI

## Summary
Build a separate Textual-based TUI entrypoint for repo operations and ATRAD portfolio viewing, without coupling it to the current automation CLI. The v1 TUI will support:
- Main menu: `Portfolio`, `Config`
- Config menu: `User`, `Orders`
- User tools: reset ATRAD `JSESSIONID`, update shared trigger defaults in `users/default.json`
- Orders tools: list, add, remove, and edit orders with option-based inputs plus manual entry fallback
- Portfolio flow: select platform (`ATRAD`, `TMS`), then ATRAD user, then open tab `1: Order Book`
- Order Book tab: fetch ATRAD active order book, sort by time, refresh with `r`, cancel selected order with `c` after confirmation showing the request URL

Decisions locked:
- Launch as a separate command/module, not inside `main.py`
- `default.json` editor only manages the shared trigger fields already supported by inheritance
- Orders editor supports the full current order schema, with mode-aware fields

## Implementation Changes

### 1. TUI package structure
Add a dedicated package, for example `tui/`, with strict separation between UI, actions, and data adapters:
- `tui/app.py`: Textual `App` bootstrap, key bindings, theme, screen routing
- `tui/screens/`: screen classes for main menu, config menu, user tools, orders list/editor, platform select, user select, order book
- `tui/widgets/`: reusable widgets such as option forms, confirmation modal, status bar, table wrapper, manual-value prompt
- `tui/controllers/`: screen-agnostic orchestration for config actions, order editing, and portfolio loading
- `tui/services/`: TUI-facing adapters over existing repo services and file operations
- `tui/models/`: lightweight display/view models for menu items, order rows, form fields, and order-book rows

Keep Textual code out of `api/`, `config/`, `services/`, and `utils/`. The TUI should call adapter/controller functions, not directly mutate files or call ATRAD endpoints from widgets.

### 2. Launch and integration
Add a separate runnable entrypoint:
- module entry such as `python -m tui.app`
- `make tui` target for convenience
- add `textual` to project dependencies in `pyproject.toml`

Do not change existing `main.py` CLI behavior. The TUI is an additional operator interface, not a replacement.

### 3. Config workflows
Create TUI adapters that reuse existing config behavior rather than duplicating JSON logic:
- `Reset JSESSIONID`: reuse the current ATRAD reset behavior, but refactor the reset logic into an importable function so the TUI and CLI utility share it
- `Update default.json`: edit only:
  - `trigger_mode_poll_interval_ms`
  - `trigger_mode_refresh_interval_seconds`
  - `trigger_sell_poll_interval_ms`
  - `trigger_mode_slow_poll_interval_ms`
  - `trigger_mode_requests_per_fetch_user`

Behavior:
- load `users/default.json` if present, otherwise create it with only those supported keys
- use typed fields with validation
- save atomically through shared file helpers
- show success/error banners in the TUI

### 4. Orders management
Refactor `OrderStore` responsibilities slightly so TUI can use them safely:
- keep existing validation logic as the source of truth
- add non-CLI mutation helpers for:
  - add order
  - update order by id
  - remove order by id
  - save store
- keep order normalization/validation centralized in one place

Orders screen behavior:
- show all orders in a table/list with key columns: id, ticker, mode, queue_id, execute, success, time
- support actions: add, edit, remove
- editing uses a mode-aware form:
  - always show common fields
  - show advanced fields only when relevant to selected mode/flags
  - for fields like time and intervals, offer preset options plus a manual input path
- removal requires confirmation
- save path remains `stores/order_store.json` unless a future screen adds store selection

### 5. Portfolio and ATRAD order book
Add a portfolio flow optimized for extension:
- Platform select screen: show `ATRAD`, `TMS`; `TMS` is disabled or marked “coming later”
- ATRAD user select screen: list available ATRAD users from `users/`
- Portfolio workspace screen: tab container with only tab `1: Order Book` in v1

Add missing ATRAD client/service support behind a portfolio adapter:
- implement a fetch method for `atrad_order_book_endpoint`
- implement a cancel-order method for `atrad_cancel_order_endpoint`
- normalize ATRAD responses into a stable `OrderBookRow` model used by the TUI
- ensure client auto-authentication/session restore happens through existing ATRAD client flow

Order Book tab behavior:
- fetch active order book on screen load
- sort rows by order time ascending or descending consistently; pick one and document it in code and tests
- `r`: refetch immediately
- `c`: open confirmation modal for selected order
- confirmation modal must show:
  - essential order identity fields
  - the fully built cancel request URL
- only send cancel after explicit confirmation
- after successful cancel, wait 1 second, then refetch order book
- show failures inline without crashing the app

### 6. Cross-cutting modularity rules
Use these boundaries so future tabs/features stay easy to add:
- Screens only manage presentation and event wiring
- Controllers decide “what action happens next”
- Services/adapters handle filesystem/API interaction
- Shared validators come from existing domain modules where possible
- No widget should know ATRAD payload formats or order-store JSON persistence details
- All long-running work should use Textual worker/background patterns so the UI never blocks during fetch/cancel/save

## Public Interfaces / Additions
Add these new outward-facing interfaces:
- a TUI entrypoint module and `make tui`
- importable config action helpers for ATRAD session reset and default-field persistence
- importable order-store mutation helpers for add/update/remove/save
- ATRAD portfolio-facing methods:
  - fetch order book
  - cancel order
- view-model types for order rows, order-book rows, and dynamic form field definitions

Do not change the existing automation CLI flags or order execution APIs in this phase.

## Test Plan
Add offline tests only; no live ATRAD/TMS calls.

### Unit tests
- config action tests:
  - reset `JSESSIONID` only for ATRAD user files
  - create/update `users/default.json`
  - reject invalid numeric values for default trigger fields
- order store mutation tests:
  - add valid order
  - edit existing order
  - remove order
  - preserve unrelated metadata/instructions
  - reject invalid fields using existing validation rules
- ATRAD portfolio adapter tests:
  - fetch order book success
  - expired session then re-auth success
  - invalid response handling
  - cancel request payload/URL generation
  - post-cancel delayed refetch trigger

### TUI behavior tests
Use Textual app/screen tests where practical:
- main menu navigation
- config menu navigation
- user action confirmation and success/error notifications
- orders list loads current store
- add/edit/remove flows update store through adapters
- platform select and ATRAD user select flow
- order book loads rows, refreshes with `r`, opens cancel modal with `c`
- cancel confirm issues adapter call and refreshes after delay

### Regression checks
- full existing `pytest` suite must still pass
- no changes to `main.py` runtime behavior
- no repo mutation from portfolio views except explicit cancel action
- TUI remains usable when `users/default.json` does not exist yet

## Assumptions and Defaults
- The “Config -> show 3 options” line is treated as a typo; v1 config menu contains `User` and `Orders`
- Order editing targets `stores/order_store.json` only in v1
- `TMS` in Portfolio is present as a placeholder but not implemented yet
- `default.json` editing is limited to the five inherited trigger fields
- Order forms support both preset choices and manual entry for fields like time/intervals
- ATRAD order book sorting will use the order timestamp field returned by the endpoint; if multiple candidate fields exist, normalize centrally in the adapter and test that mapping
- Cancel confirmation shows the final request URL string and only executes after explicit user confirmation
