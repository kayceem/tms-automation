"""Probe the TMS stock quote WebSocket directly from Python."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.models.user_config import UserConfig
from api.tms_client import TMSClient

try:
    import websocket
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    raise SystemExit(
        "Missing dependency `websocket-client`. Install project dependencies first, "
        "for example with `uv sync`."
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("security_id", help="Security id or exchange security id to subscribe to")
    parser.add_argument(
        "--user-config",
        default="examples/tms.user.json",
        help="Path to a TMS user JSON file with cookies and session fields",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=10.0,
        help="Socket timeout for connect and receive operations",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=500,
        help="Stop after collecting this many matching stock quote frames",
    )
    parser.add_argument(
        "--show-all-frames",
        action="store_true",
        help="Print every inbound frame instead of only @data,stockquote frames",
    )
    return parser.parse_args()


def build_ws_url(config: UserConfig) -> tuple[str, dict[str, str]]:
    parsed = urlparse(config.tms_base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    session_params = {
        "memberId": str(config.member_id or config.member_code),
        "clientId": str((config.client_data or {}).get("id") or ""),
        "dealerId": "",
        "userId": str(config.request_owner),
    }
    url = f"{scheme}://{parsed.netloc}/tmsapi/socket?{urlencode(session_params)}"
    return url, session_params


def build_subscribe_message(argument: str) -> dict[str, Any]:
    return {
        "header": {
            "channel": "@control",
            "transaction": "start_stockquote",
        },
        "payload": {
            "argument": str(argument),
        },
    }


def build_stop_message() -> dict[str, Any]:
    return {
        "header": {
            "channel": "@control",
            "transaction": "stop_stockquote",
        },
        "payload": {
            "argument": "undefined",
        },
    }


def build_headers(config: UserConfig) -> list[str]:
    cookie_parts = [
        f"_rid={config.rid_cookie}",
        f"_aid={config.access_token}",
        f"XSRF-TOKEN={config.xsrf_token}",
    ]
    return [
        f"Origin: {config.tms_base_url}",
        f"Host: {config.tms_host}",
        "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0",
        "Pragma: no-cache",
        f"Cookie: {'; '.join(cookie_parts)}",
        "sec-websocket-extensions: permessage-deflate; client_max_window_bits",
        "sec-websocket-version: 13",
        "upgrade: websocket",
        "connection: Upgrade",
        "accept-encoding: gzip, deflate, br, zstd",
        "accept-language: en-US,en;q=0.9",
    ]


def normalize_messages(raw_data: str) -> list[dict[str, Any]]:
    parsed = json.loads(raw_data)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


def print_stockquote_summary(record: dict[str, Any]) -> None:
    payload = record.get("payload") or {}
    data = payload.get("data") or []
    if not data:
        print("Stockquote received: empty payload")
        return

    received_at_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    quote = data[0]
    security = quote.get("security") or {}
    symbol = security.get("symbol") or "?"
    security_id = security.get("id") or "?"
    ltp = quote.get("ltp")
    change = quote.get("change")
    change_percentage = quote.get("changePercentage")
    last_traded_time = quote.get("lastTradedTime")
    print(
        f"{received_at_str} "
        f"symbol={symbol} ltp={ltp} "
        f"change={change} change_percentage={change_percentage} "
        f"last_traded_time={last_traded_time}"
    )


def probe(args: argparse.Namespace) -> int:
    config = UserConfig.from_file(args.user_config)
    client = TMSClient(config)
    ws_url, session_params = build_ws_url(config)
    subscribe_message = build_subscribe_message(args.security_id)
    stop_message = build_stop_message()

    print(f"Base URL: {config.tms_base_url}")
    print(f"WS URL:   {ws_url}")
    print(f"WS params: {json.dumps(session_params, indent=2)}")
    print("Refreshing tokens before connecting...")
    if client.refresh_tokens():
        print("Token refresh successful")
    else:
        print("Token refresh failed; continuing with existing session")
    print("Subscribe message:")
    print(json.dumps(subscribe_message, indent=2))
    print("Stop message:")
    print(json.dumps(stop_message, indent=2))

    websocket.enableTrace(False)
    ws = None
    matching_frames: list[dict[str, Any]] = []
    all_frames: list[dict[str, Any]] = []

    try:
        ws = websocket.create_connection(
            ws_url,
            timeout=args.timeout_seconds,
            header=build_headers(config),
            suppress_origin=False,
        )
        print("Socket opened")
        ws.send(json.dumps(subscribe_message))
        print("Subscribe message sent")

        while len(matching_frames) < args.max_messages:
            raw_frame = ws.recv()
            messages = normalize_messages(raw_frame)
            for message in messages:
                header = message.get("header") or {}
                payload = message.get("payload")
                record = {
                    "header": header,
                    "payload": payload,
                }
                if args.show_all_frames:
                    all_frames.append(record)
                if header.get("channel") == "@data" and header.get("transaction") == "stockquote":
                    matching_frames.append(record)
                    print_stockquote_summary(record)
            if args.show_all_frames and len(all_frames) >= args.max_messages:
                break

    except websocket.WebSocketBadStatusException as exc:
        print(f"Handshake failed: status={exc.status_code}")
        if exc.resp_headers:
            print("Response headers:")
            print(json.dumps(dict(exc.resp_headers), indent=2))
        return 1
    except KeyboardInterrupt:
        print("Interrupted by user")
        return 130
    except websocket.WebSocketTimeoutException:
        print("Timed out waiting for frames")
        return 1
    except Exception as exc:
        print(f"Probe failed: {exc}")
        return 1
    finally:
        if ws is not None:
            try:
                ws.send(json.dumps(stop_message))
                print("Stop message sent")
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass

    result_frames = all_frames if args.show_all_frames else matching_frames
    print("Captured frames:")
    print(json.dumps(result_frames, indent=2))

    if not result_frames:
        print("No matching frames were captured")
        return 1
    return 0


def main() -> int:
    return probe(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
