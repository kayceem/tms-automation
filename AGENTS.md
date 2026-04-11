# Repository Guidelines

## Project Structure & Module Organization
`main.py` is the entry point for order execution and scheduling. Core platform clients live in `api/`, business logic in `services/`, shared configuration models in `config/`, and rceusable helpers in `utils/`. Token automation is isolated in `token_fetcher/`. Runtime JSON data lives in `stores/` and `users/`; treat both as environment-specific inputs, not source code. Reference payloads and examples are in `examples/` and `docs/`.

## Build, Test, and Development Commands
Use Python 3.12+ with the locked dependencies from `uv.lock`.

- `uv sync` installs project dependencies into the local environment.
- `python main.py --help` shows all runtime flags for manual execution.
- `make run` runs the default TMS workflow with `stores/order_store.json`.
- `make runaf TIME=10:30` runs the ATRAD fetch flow and optionally overrides the first scheduled order time.
- `make update` refreshes user tokens from the `users/` directory.
- `make prepare` resets ATRAD tokens and updates stored order prices before a session.
- `pytest` runs automated tests discovered under `tests/`.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, snake_case for functions, variables, files, and JSON keys, and PascalCase for classes such as `TMSClient` and `ATRADOrderService`. Keep modules focused by platform or responsibility. Prefer small helper functions in `utils/` over duplicating request, logging, or store logic. Match current CLI flag and config naming patterns such as `--order-store` and `timeout_ipo_trigger_low`.

## Testing Guidelines
Pytest is configured in `pyproject.toml` to run only files under `tests/`. Add new tests as `tests/test_<feature>.py`. Keep unit tests deterministic; mock external TMS/ATRAD requests instead of hitting live endpoints. If a change affects JSON-driven workflows, include a representative fixture or example payload in `examples/` when useful. There is little test coverage today, so new behavior should ship with targeted tests where practical.

## Commit & Pull Request Guidelines
Recent history uses short imperative subjects with prefixes like `add:` and `update:`. Keep that format, for example: `update: handle multi-queue timeout`. Scope each commit to one behavioral change. PRs should include a concise summary, affected commands or stores, any required `.env` or user-config changes, and sample logs or screenshots when execution flow changes.

## Security & Configuration Tips
Do not commit live credentials, tokens, or personal user JSON. Start from `.env.example`, keep secrets in `.env`, and sanitize `users/`, `stores/`, and `logs/` content before sharing.
