import json
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Callable, Optional

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ATRADUserConfig, UserConfig


@dataclass
class Route:
    method: str
    matcher: Any
    response_factory: Callable[..., Any]

    def matches(self, method: str, url: str) -> bool:
        if method.upper() != self.method:
            return False
        matcher = self.matcher
        if isinstance(matcher, str):
            return url == matcher
        if isinstance(matcher, re.Pattern):
            return bool(matcher.search(url))
        if callable(matcher):
            return bool(matcher(url))
        raise TypeError(f"Unsupported matcher type: {type(matcher)!r}")


class HttpInterceptor:
    def __init__(self) -> None:
        self._routes: deque[Route] = deque()
        self.calls: list[dict[str, Any]] = []

    def add_json(
        self,
        method: str,
        matcher: Any,
        *,
        status: int = 200,
        payload: Optional[Any] = None,
        text: Optional[str] = None,
        cookies: Optional[list[dict[str, Any]]] = None,
        reason: str = "OK",
    ) -> None:
        def factory(**_: Any) -> requests.Response:
            body = text
            if body is None:
                body = json.dumps(payload if payload is not None else {})
            return build_response(
                status=status,
                text=body,
                reason=reason,
                cookies=cookies,
                content_type="application/json",
            )

        self._routes.append(Route(method=method.upper(), matcher=matcher, response_factory=factory))

    def add_text(
        self,
        method: str,
        matcher: Any,
        *,
        status: int = 200,
        text: str = "",
        cookies: Optional[list[dict[str, Any]]] = None,
        reason: str = "OK",
    ) -> None:
        def factory(**_: Any) -> requests.Response:
            return build_response(
                status=status,
                text=text,
                reason=reason,
                cookies=cookies,
                content_type="text/plain",
            )

        self._routes.append(Route(method=method.upper(), matcher=matcher, response_factory=factory))

    def add_exception(self, method: str, matcher: Any, exc: Exception) -> None:
        def factory(**_: Any) -> Exception:
            return exc

        self._routes.append(Route(method=method.upper(), matcher=matcher, response_factory=factory))

    def request(self, session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append(
            {
                "method": method.upper(),
                "url": url,
                "kwargs": kwargs,
            }
        )

        for route in list(self._routes):
            if route.matches(method, url):
                self._routes.remove(route)
                result = route.response_factory(method=method.upper(), url=url, kwargs=kwargs)
                if isinstance(result, Exception):
                    raise result
                session.cookies.update(result.cookies)
                result.url = url
                return result

        raise AssertionError(f"Unexpected HTTP request: {method.upper()} {url}")

    def assert_all_consumed(self) -> None:
        if self._routes:
            pending = [f"{route.method} {route.matcher!r}" for route in self._routes]
            raise AssertionError(f"Unconsumed HTTP routes: {pending}")


def build_response(
    *,
    status: int,
    text: str,
    reason: str = "OK",
    cookies: Optional[list[dict[str, Any]]] = None,
    content_type: str = "application/json",
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.reason = reason
    response.encoding = "utf-8"
    response._content = text.encode("utf-8")
    response.headers["Content-Type"] = content_type

    jar = requests.cookies.RequestsCookieJar()
    for cookie in cookies or []:
        jar.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    response.cookies = jar
    return response


@pytest.fixture
def http_interceptor(monkeypatch: pytest.MonkeyPatch) -> HttpInterceptor:
    interceptor = HttpInterceptor()

    def fake_request(session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
        return interceptor.request(session, method, url, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    yield interceptor
    interceptor.assert_all_consumed()


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)


@pytest.fixture
def tms_user_config(tmp_path: Path) -> UserConfig:
    config_path = tmp_path / "tms_user.json"
    config_path.write_text(
        json.dumps(
            {
                "user_id": "tms-user",
                "tms_host": "example.test",
                "tms_base_url": "https://example.test",
                "xsrf_token": "xsrf-token",
                "rid_cookie": "rid-cookie",
                "host_session_id": "host-session",
                "access_token": "access-token",
                "request_owner": "request-owner",
                "member_code": "123",
                "client_data": {"id": 42, "name": "Trader"},
            }
        ),
        encoding="utf-8",
    )
    return UserConfig.from_file(str(config_path))


@pytest.fixture
def atrad_user_config(tmp_path: Path) -> ATRADUserConfig:
    config_path = tmp_path / "atrad_user.json"
    config_path.write_text(
        json.dumps(
            {
                "user_id": "atrad-user",
                "atrad_base_url": "https://atrad.test",
                "atrad_host": "atrad.test",
                "username": "demo-user",
                "password": "demo-pass",
                "account_id": "ACC-1",
                "client_account": "ACC (PRIMARY)",
                "broker_code": "NSH",
                "contra_broker": "0",
            }
        ),
        encoding="utf-8",
    )
    return ATRADUserConfig.from_file(str(config_path))
