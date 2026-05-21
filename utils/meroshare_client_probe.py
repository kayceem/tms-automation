"""Probe login, portfolio, and WACC using the real MeroShareClient."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from api import MeroShareClient
from config.models import MeroShareUserConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe MeroShareClient behavior against live MeroShare endpoints.")
    parser.add_argument(
        "--user-config",
        default="users/meroshare_user1.json",
        help="Path to MeroShare user JSON config.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds.")
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="Ignore any saved authorization for this probe and force login first.",
    )
    return parser.parse_args()


def classify_exception(exc: BaseException) -> str:
    text = str(exc)
    support_match = re.search(r"support ID is:\s*([0-9]+)", text, re.IGNORECASE)
    support = f" support_id={support_match.group(1)}" if support_match else ""
    if "Request Rejected" in text or "<html" in text.lower():
        return f"HTML rejected{support}"
    return text.replace("\n", " ")[:240]


def classify_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        keys = ", ".join(list(payload.keys())[:8])
        return f"dict keys=[{keys}]"
    if isinstance(payload, list):
        return f"list length={len(payload)}"
    return type(payload).__name__


def print_step(name: str, ok: bool, detail: str) -> None:
    status = "OK" if ok else "FAIL"
    print(f"{name:<18} {status:<4} {detail}")


def run_step(name: str, func: Callable[[], Any], summarize: Callable[[Any], str]) -> Any:
    try:
        result = func()
    except Exception as exc:
        print_step(name, False, classify_exception(exc))
        return None
    print_step(name, True, summarize(result))
    return result


def main() -> int:
    args = parse_args()
    config = MeroShareUserConfig.from_file(args.user_config)
    if args.force_login:
        config._headers.pop("authorization", None)
        config._headers.pop("Authorization", None)

    client = MeroShareClient(config)
    print(client.is_authenticated())
    print(client.session.headers)
    print(client.session.cookies)
    print(f"user_id={config.user_id} username={config.username} demat={config.demat}")
    print(f"base_url={config.meroshare_base_url}")
    print(f"initial_authenticated={client.is_authenticated()} cookies={len(client.session.cookies)}")

    login_payload = run_step(
        "login",
        lambda: client.login(timeout=args.timeout),
        lambda payload: f"{classify_payload(payload)} authenticated={client.is_authenticated()} cookies={len(client.session.cookies)}",
    )

    portfolio_rows = run_step(
        "portfolio",
        lambda: client.get_portfolio(timeout=args.timeout),
        lambda rows: f"rows={len(rows)} cookies={len(client.session.cookies)} sample={sample_symbol(rows)}",
    )

    wacc_payload = run_step(
        "wacc",
        lambda: client.get_wacc_report(timeout=args.timeout),
        lambda payload: f"rows={len(payload.get('waccReportResponse', [])) if isinstance(payload, dict) else '-'} cookies={len(client.session.cookies)}",
    )

    return 0 if login_payload is not None and portfolio_rows is not None and wacc_payload is not None else 1


def sample_symbol(rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return "-"
    first = rows[0]
    if not isinstance(first, dict):
        return "-"
    return str(first.get("script") or first.get("scrip") or "-")


if __name__ == "__main__":
    raise SystemExit(main())
