"""Probe MeroShare auth/portfolio/WACC behavior with system curl.

This is diagnostic only. It reads a MeroShare user config, performs the
browser-shaped curl login, then compares API calls with token-only versus
token+login-cookies to identify what CDSC is rejecting.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import sys

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.models import MeroShareUserConfig


@dataclass
class CurlResult:
    name: str
    status: int | None
    content_type: str
    body: str
    headers: dict[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe MeroShare endpoints with system curl.")
    parser.add_argument(
        "--user-config",
        default="users/meroshare_user1.json",
        help="Path to a MeroShare user JSON config.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Curl max-time in seconds.")
    return parser.parse_args()


def frontend_origin(config: MeroShareUserConfig) -> str:
    host = config.meroshare_host_url.strip().rstrip("/")
    if host.startswith(("http://", "https://")):
        return host
    return f"https://{host}"


def common_headers(config: MeroShareUserConfig, *, authorization: str) -> list[str]:
    origin = frontend_origin(config)
    return [
        "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0",
        "Accept: application/json, text/plain, */*",
        "Accept-Language: en-US,en;q=0.9",
        "Accept-Encoding: gzip, deflate, br, zstd",
        f"Referer: {origin}/",
        f"Authorization: {authorization}",
        "Content-Type: application/json",
        f"Origin: {origin}",
        "Sec-GPC: 1",
        "Connection: keep-alive",
        "Sec-Fetch-Dest: empty",
        "Sec-Fetch-Mode: cors",
        "Sec-Fetch-Site: same-site",
    ]


def endpoint(config: MeroShareUserConfig, path: str) -> str:
    return f"{config.meroshare_base_url.rstrip('/')}{path}"


def parse_headers(path: Path) -> tuple[int | None, str, dict[str, str]]:
    blocks = path.read_text(encoding="utf-8", errors="replace").strip().split("\n\n")
    latest = blocks[-1] if blocks and blocks[-1] else ""
    status: int | None = None
    headers: dict[str, str] = {}
    for index, line in enumerate(latest.splitlines()):
        line = line.strip()
        if index == 0 and line.startswith("HTTP/"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.lower()] = value.strip()
    return status, headers.get("content-type", ""), headers


def run_curl(
    *,
    name: str,
    config: MeroShareUserConfig,
    url: str,
    method: str,
    payload: dict[str, Any] | None,
    authorization: str,
    cookie_jar: Path | None,
    timeout: float,
    compact_body: bool = True,
) -> CurlResult:
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as header_file:
        header_path = Path(header_file.name)

    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--http1.1",
        "--max-time",
        str(timeout),
        "--dump-header",
        str(header_path),
        "-X",
        method,
    ]
    if cookie_jar is not None:
        command.extend(["--cookie-jar", str(cookie_jar), "--cookie", str(cookie_jar)])
    for header in common_headers(config, authorization=authorization):
        command.extend(["-H", header])
    if payload is not None:
        if compact_body:
            body = json.dumps(payload, separators=(",", ":"))
        else:
            body = json.dumps(payload)
        command.extend(["--data-raw", body])
    command.append(url)

    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        status, content_type, headers = parse_headers(header_path)
        body = completed.stdout or completed.stderr
        if completed.returncode != 0 and not body:
            body = f"curl failed with exit code {completed.returncode}"
        return CurlResult(name=name, status=status, content_type=content_type, body=body, headers=headers)
    finally:
        header_path.unlink(missing_ok=True)


def run_requests(
    *,
    name: str,
    config: MeroShareUserConfig,
    url: str,
    method: str,
    payload: dict[str, Any] | None,
    authorization: str,
    timeout: float,
    compact_body: bool,
) -> CurlResult:
    session = requests.Session()
    headers = {
        key: value
        for key, value in (
            header.split(": ", 1)
            for header in common_headers(config, authorization=authorization)
        )
    }
    session.headers.update(headers)
    kwargs: dict[str, Any] = {"timeout": timeout}
    if payload is not None:
        if compact_body:
            kwargs["data"] = json.dumps(payload, separators=(",", ":"))
        else:
            kwargs["json"] = payload
    response = session.request(method, url, **kwargs)
    return CurlResult(
        name=name,
        status=response.status_code,
        content_type=response.headers.get("Content-Type", ""),
        body=response.text,
        headers={key.lower(): value for key, value in response.headers.items()},
    )


def classify_body(body: str) -> str:
    stripped = (body or "").strip()
    if not stripped:
        return "empty"
    if stripped.lower().startswith("<html") or "Request Rejected" in stripped:
        support_match = re.search(r"support ID is:\s*([0-9]+)", stripped, re.IGNORECASE)
        support_id = f", support_id={support_match.group(1)}" if support_match else ""
        return f"HTML rejected{support_id}"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return f"non-JSON: {stripped[:120]}"
    if isinstance(payload, dict):
        keys = ", ".join(list(payload.keys())[:8])
        return f"JSON object keys=[{keys}]"
    if isinstance(payload, list):
        return f"JSON list length={len(payload)}"
    return f"JSON {type(payload).__name__}"


def print_result(result: CurlResult) -> None:
    auth_present = "yes" if result.headers.get("authorization") else "no"
    print(
        f"{result.name:<28} status={result.status} "
        f"content_type={result.content_type or '-'} response_auth={auth_present} "
        f"{classify_body(result.body)}"
    )


def main() -> int:
    if shutil.which("curl") is None:
        raise SystemExit("curl binary not found")

    args = parse_args()
    config = MeroShareUserConfig.from_file(args.user_config)
    login_payload = {
        "clientId": config.client_id_int,
        "username": config.username,
        "password": config.password,
    }
    portfolio_payload = {
        "sortBy": "script",
        "demat": [config.demat],
        "clientCode": config.client_code,
        "page": 1,
        "size": 200,
        "sortAsc": True,
    }
    wacc_payload = {"demat": config.demat}

    with tempfile.TemporaryDirectory(prefix="meroshare-curl-probe-") as tmp_dir:
        cookie_jar = Path(tmp_dir) / "cookies.txt"
        login = run_curl(
            name="login",
            config=config,
            url=endpoint(config, config.meroshare_login_endpoint),
            method="POST",
            payload=login_payload,
            authorization="null",
            cookie_jar=cookie_jar,
            timeout=args.timeout,
        )
        print_result(login)

        token = login.headers.get("authorization")
        if not token:
            print("login did not return Authorization; stopping endpoint comparison")
            return 1

        probes = [
            (
                "details token only",
                endpoint(config, f"{config.meroshare_details_endpoint}{config.demat}"),
                "GET",
                None,
                None,
            ),
            (
                "details token+cookies",
                endpoint(config, f"{config.meroshare_details_endpoint}{config.demat}"),
                "GET",
                None,
                cookie_jar,
            ),
            (
                "portfolio token only",
                endpoint(config, config.meroshare_portfolio_endpoint),
                "POST",
                portfolio_payload,
                None,
            ),
            (
                "portfolio token+cookies",
                endpoint(config, config.meroshare_portfolio_endpoint),
                "POST",
                portfolio_payload,
                cookie_jar,
            ),
            (
                "wacc token only",
                endpoint(config, config.meroshare_wacc_endpoint),
                "POST",
                wacc_payload,
                None,
            ),
            (
                "wacc token+cookies",
                endpoint(config, config.meroshare_wacc_endpoint),
                "POST",
                wacc_payload,
                cookie_jar,
            ),
        ]
        for name, url, method, payload, cookies in probes:
            print_result(
                run_curl(
                    name=name,
                    config=config,
                    url=url,
                    method=method,
                    payload=payload,
                    authorization=token,
                    cookie_jar=cookies,
                    timeout=args.timeout,
                )
            )
        portfolio_url = endpoint(config, config.meroshare_portfolio_endpoint)
        print_result(
            run_curl(
                name="portfolio curl spaced JSON",
                config=config,
                url=portfolio_url,
                method="POST",
                payload=portfolio_payload,
                authorization=token,
                cookie_jar=None,
                timeout=args.timeout,
                compact_body=False,
            )
        )
        print_result(
            run_requests(
                name="portfolio requests json=",
                config=config,
                url=portfolio_url,
                method="POST",
                payload=portfolio_payload,
                authorization=token,
                timeout=args.timeout,
                compact_body=False,
            )
        )
        print_result(
            run_requests(
                name="portfolio requests compact",
                config=config,
                url=portfolio_url,
                method="POST",
                payload=portfolio_payload,
                authorization=token,
                timeout=args.timeout,
                compact_body=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
