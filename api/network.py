"""Shared network helpers for API clients."""

import socket


def create_ipv4_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, socket_options=None):
    """Create socket connection using IPv4 only."""
    host, port = address
    err = None
    for res in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        af, socktype, proto, _, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            if socket_options:
                for opt in socket_options:
                    sock.setsockopt(*opt)
            sock.connect(sa)
            return sock
        except socket.error as exc:
            err = exc
            if sock is not None:
                sock.close()
    if err is not None:
        raise err
    raise socket.error("getaddrinfo returns an empty list")


def enable_ipv4_only_requests() -> None:
    """Monkey-patch urllib3 connections to prefer IPv4 only."""
    urllib3_connection = __import__("urllib3.util.connection", fromlist=["connection"])
    urllib3_connection.create_connection = create_ipv4_connection
