# Project Summary

## Overview
This repository automates NEPSE order execution for both TMS and ATRAD users. It supports direct orders, scheduled execution, IPO trigger flows, trigger-sell logic, multi-queue orchestration, and coordinated sell/buy trigger scenarios. The current codebase has been refactored to separate orchestration, platform adapters, workflow logic, and configuration loading.

## Current Architecture

### Entry and App Layer
- `main.py`: thin CLI entrypoint
- `app/cli.py`: argument parsing and validation
- `app/config_loader.py`: main/fetch/seller/buyer config loading
- `app/execution.py`: runtime orchestration for manual orders, order stores, and scheduled flows
- `app/factories.py`, `app/models.py`, `app/order_requests.py`: shared request building and platform wiring

### API Layer
- `api/tms_client.py`: TMS login, refresh, order, and quote operations
- `api/atrad_client.py`: ATRAD login/session/order/quote operations
- `api/network.py`: shared networking setup such as IPv4 forcing

### Services
- `services/orders/`: order execution services and shared dispatch helpers
- `services/fetchers/`: TMS/ATRAD price fetchers and multi-symbol polling
- `services/scheduling/`: time-based execution and token refresh scheduling
- `services/workflows/`: extracted workflow modules for ladders, polling waits, retry helpers, specialized trigger paths, and coordinated flows

### Config
- `config/models/`: `UserConfig` and `ATRADUserConfig`
- `config/loaders/`: file loading, system-aware config loading, and default inheritance
- `config/settings.py`: environment-backed runtime settings

## Config Behavior
- User files may omit these trigger tuning fields:
  - `trigger_mode_poll_interval_ms`
  - `trigger_mode_refresh_interval_seconds`
  - `trigger_sell_poll_interval_ms`
  - `trigger_mode_slow_poll_interval_ms`
  - `trigger_mode_requests_per_fetch_user`
- When omitted, values are inherited from a sibling `default.json`.
- Inherited values are runtime defaults only. They are not written back into user files during save/update operations.

## Test Baseline
The project now has an offline pytest characterization suite with intercepted HTTP requests. No live TMS or ATRAD calls are required for normal test runs.

Covered areas:
- TMS and ATRAD API clients
- config loading and default inheritance
- order store validation and persistence
- scheduler behavior
- service dispatch and base workflow helpers
- `main.py` orchestration paths

Current baseline:
- `pytest`
- Result: `67 passed`

## Notable Refactor Outcomes
- `main.py` is no longer the orchestration monolith.
- `BaseOrderService` logic has been split into focused workflow modules.
- `services/` and `config/` are organized by responsibility instead of flat file growth.
- repeated request-building and config-loading logic has been centralized.
- logging now uses the shared `main` logger consistently instead of module-specific logger trees.

## Next Safe Improvement Areas
- continue reducing duplication inside API session-refresh flows if deeper cleanup is needed
- add more characterization coverage before any future behavior changes in live trading paths
