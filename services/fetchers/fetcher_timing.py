"""Shared timing helpers for polling-based price fetchers."""


def calculate_request_timeout(poll_interval_seconds: float) -> float:
    """Derive a bounded request timeout from the polling interval."""
    return max(min(poll_interval_seconds * 4, 0.05), 0.025)


def calculate_rotation_delay(poll_interval_seconds: float, minimum_delay: float) -> float:
    """Derive an inter-request delay for multi-user rotation fetchers."""
    return max(minimum_delay, poll_interval_seconds / 2)
