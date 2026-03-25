#!/usr/bin/env python3
"""
Script to test rate limits on TMS API endpoints.
Measures how many requests per minute are allowed before rate limiting occurs.
"""

import requests
import time
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import argparse
from collections import defaultdict
from dataclasses import dataclass
import logging


class MillisecondFormatter(logging.Formatter):
    """Custom formatter that includes milliseconds in the timestamp."""

    def formatTime(self, record, datefmt=None):
        """Format time with milliseconds."""
        ct = self.converter(record.created)
        t = time.strftime("%Y-%m-%d %H:%M:%S", ct)
        return "%s.%03d" % (t, record.msecs)


def setup_logger(name: str = "rate_limit_tester", log_file: Optional[str] = None) -> logging.Logger:
    """
    Set up logger with millisecond precision.

    Args:
        name: Logger name
        log_file: Optional file path to save logs

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatter with milliseconds
    formatter = MillisecondFormatter(
        fmt='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


@dataclass
class User:
    """Represents a user with their own credentials and session."""
    name: str
    headers: Dict[str, str]
    cookies: Dict[str, str]
    session: requests.Session = None

    def __post_init__(self):
        """Initialize the session with headers and cookies."""
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update(self.headers)
            if self.cookies:
                for key, value in self.cookies.items():
                    self.session.cookies.set(key, value)


class RateLimitTester:
    """Test rate limits for HTTP endpoints with multiple user support."""

    def __init__(self, url: str, users: List[User],
                 refresh_endpoint: Optional[str] = None,
                 auto_refresh_on_401: bool = True,
                 requests_per_user: int = 1,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize rate limit tester with multiple users.

        Args:
            url: The endpoint URL to test
            users: List of User objects with their credentials
            refresh_endpoint: Optional token refresh endpoint URL
            auto_refresh_on_401: Automatically refresh tokens on 401 errors (default: True)
            requests_per_user: Number of requests per user before rotating (default: 1 for round-robin)
            logger: Optional logger instance (will create default if not provided)
        """
        self.url = url
        self.users = users
        self.refresh_endpoint = refresh_endpoint
        self.auto_refresh_on_401 = auto_refresh_on_401
        self.requests_per_user = requests_per_user
        self.current_user_index = 0
        self.requests_with_current_user = 0
        self.logger = logger or logging.getLogger('rate_limit_tester')

    def _get_next_user(self) -> User:
        """
        Get the next user in rotation.

        Returns:
            User object to use for the next request
        """
        # Check if we should rotate to next user FIRST
        if self.requests_with_current_user >= self.requests_per_user:
            self.current_user_index = (self.current_user_index + 1) % len(self.users)
            self.requests_with_current_user = 0

        self.requests_with_current_user += 1
        return self.users[self.current_user_index]

    def test_rate_limit(
        self,
        duration_seconds: int = 60,
        max_requests: int = 1000,
        delay_between_requests: float = 0.0,
        method: str = "GET",
        payload: Optional[Dict] = None
    ) -> Dict:
        """
        Test rate limit by sending requests continuously.

        Args:
            duration_seconds: How long to run the test (default: 60s)
            max_requests: Maximum number of requests to send
            delay_between_requests: Delay in seconds between requests (default: 0)
            method: HTTP method (GET, POST, etc.)
            payload: Optional JSON payload for POST requests

        Returns:
            Dictionary with test results
        """
        results = {
            'url': self.url,
            'start_time': datetime.now().isoformat(),
            'duration_seconds': duration_seconds,
            'num_users': len(self.users),
            'requests_per_user_rotation': self.requests_per_user,
            'requests_sent': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'rate_limited_requests': 0,
            'status_codes': defaultdict(int),
            'response_times': [],
            'errors': [],
            'rate_limit_detected_at': None,
            'requests_per_minute': 0,
            'user_stats': {user.name: {
                'requests': 0,
                'successful': 0,
                'failed': 0,
                'rate_limited': 0,
            } for user in self.users},
            'request_log': []  # Detailed log of each request with ms timestamps
        }

        start_time = time.time()
        end_time = start_time + duration_seconds
        first_rate_limit = None

        self.logger.info("=" * 70)
        self.logger.info(f"Starting rate limit test for: {self.url}")
        self.logger.info(f"Duration: {duration_seconds} seconds")
        self.logger.info(f"Max requests: {max_requests}")
        self.logger.info(f"Method: {method}")
        self.logger.info(f"Users: {len(self.users)} ({', '.join(u.name for u in self.users)})")
        self.logger.info(f"Rotation: Every {self.requests_per_user} request(s)")
        self.logger.info("=" * 70)

        request_count = 0

        try:
            while time.time() < end_time and request_count < max_requests:
                request_count += 1
                request_start = time.time()
                request_start_ms = int(request_start * 1000)  # Convert to milliseconds

                # Get the user for this request
                current_user = self._get_next_user()

                try:
                    # Log request initiation with ms precision
                    self.logger.debug(f"Request #{request_count:4d} | User: {current_user.name:8s} | Starting...")

                    # Make request with current user's session
                    if method.upper() == "POST":
                        response = current_user.session.post(self.url, json=payload, timeout=10)
                    elif method.upper() == "GET":
                        response = current_user.session.get(self.url, timeout=10)
                    else:
                        response = current_user.session.request(method, self.url, json=payload, timeout=10)

                    request_end = time.time()
                    request_end_ms = int(request_end * 1000)
                    request_time = request_end - request_start

                    results['response_times'].append(request_time)
                    results['requests_sent'] += 1
                    results['user_stats'][current_user.name]['requests'] += 1

                    # Calculate batch for logging
                    user_batch = (results['user_stats'][current_user.name]['requests'] // self.requests_per_user) + 1

                    # Log detailed request info with ms timestamps
                    request_log_entry = {
                        'request_number': request_count,
                        'user': current_user.name,
                        'user_batch': user_batch,
                        'timestamp_start_ms': request_start_ms,
                        'timestamp_end_ms': request_end_ms,
                        'duration_ms': int(request_time * 1000),
                        'status_code': response.status_code,
                        'time_since_start_ms': int((request_start - start_time) * 1000)
                    }
                    results['request_log'].append(request_log_entry)

                    # Log with ms precision
                    self.logger.debug(
                        f"Request #{request_count:4d} | "
                        f"User: {current_user.name:8s} | "
                        f"Status: {response.status_code} | "
                        f"Duration: {int(request_time * 1000):4d}ms | "
                        f"Time: {int((request_start - start_time) * 1000):6d}ms"
                    )

                    # Handle 401 with automatic token refresh
                    if response.status_code == 401 and self.auto_refresh_on_401 and self.refresh_endpoint:
                        self.logger.warning(f"[{current_user.name}] Session expired at request #{request_count}, attempting token refresh...")
                        if self._refresh_tokens(current_user):
                            self.logger.info(f"[{current_user.name}] Tokens refreshed successfully, retrying request #{request_count}")
                            # Retry the request with new tokens
                            retry_start = time.time()
                            if method.upper() == "POST":
                                response = current_user.session.post(self.url, json=payload, timeout=10)
                            elif method.upper() == "GET":
                                response = current_user.session.get(self.url, timeout=10)
                            else:
                                response = current_user.session.request(method, self.url, json=payload, timeout=10)
                            request_end = time.time()
                            request_time = request_end - retry_start
                            # Update log entry with retry info
                            request_log_entry['retried'] = True
                            request_log_entry['timestamp_end_ms'] = int(request_end * 1000)
                            request_log_entry['duration_ms'] = int(request_time * 1000)
                            request_log_entry['status_code'] = response.status_code
                        else:
                            self.logger.error(f"[{current_user.name}] Token refresh failed")

                    # Track status code
                    results['status_codes'][response.status_code] += 1

                    # Check for rate limiting
                    if response.status_code == 429:  # Too Many Requests
                        results['rate_limited_requests'] += 1
                        results['user_stats'][current_user.name]['rate_limited'] += 1
                        request_log_entry['rate_limited'] = True
                        if first_rate_limit is None:
                            first_rate_limit = request_count
                            results['rate_limit_detected_at'] = request_count
                            self.logger.warning(f"RATE LIMIT DETECTED at request #{request_count} [{current_user.name}]")
                            self.logger.warning(f"   Response: {response.status_code} {response.reason}")
                            if 'Retry-After' in response.headers:
                                self.logger.warning(f"   Retry-After: {response.headers['Retry-After']}s")
                                request_log_entry['retry_after'] = response.headers['Retry-After']

                    # Check for other error status codes that might indicate rate limiting
                    elif response.status_code in [503, 509, 403]:
                        results['failed_requests'] += 1
                        results['user_stats'][current_user.name]['failed'] += 1
                        request_log_entry['error'] = True
                        if first_rate_limit is None:
                            # Could be rate limiting with different status code
                            self.logger.warning(f"Possible rate limit at request #{request_count} [{current_user.name}]")
                            self.logger.warning(f"   Response: {response.status_code} {response.reason}")
                    elif response.status_code >= 400:
                        results['failed_requests'] += 1
                        results['user_stats'][current_user.name]['failed'] += 1
                        request_log_entry['error'] = True
                    else:
                        results['successful_requests'] += 1
                        results['user_stats'][current_user.name]['successful'] += 1

                    # Print progress every 10 requests
                    if request_count % 10 == 0:
                        elapsed = time.time() - start_time
                        rpm = (request_count / elapsed) * 60 if elapsed > 0 else 0
                        self.logger.info(
                            f"Request #{request_count:4d} | "
                            f"User: {current_user.name:8s} | "
                            f"Status: {response.status_code} | "
                            f"Time: {request_time * 1000:6.1f}ms | "
                            f"Rate: {rpm:.1f} req/min"
                        )

                except requests.Timeout:
                    results['errors'].append({
                        'request_number': request_count,
                        'error': 'Timeout',
                        'time': time.time() - start_time
                    })
                    self.logger.error(f"Request #{request_count:4d} | User: {current_user.name:8s} | TIMEOUT")

                except requests.RequestException as e:
                    results['errors'].append({
                        'request_number': request_count,
                        'error': str(e),
                        'time': time.time() - start_time
                    })
                    self.logger.error(f"Request #{request_count:4d} | User: {current_user.name:8s} | ERROR: {str(e)}")

                # Delay between requests if specified
                if delay_between_requests > 0:
                    time.sleep(delay_between_requests)
                # if request_count % 10 == 0:
                #     print(f"Sleeping for {delay_between_requests}s between requests...")
                #     time.sleep(2)

        except KeyboardInterrupt:
            self.logger.warning("Test interrupted by user")

        # Calculate final statistics
        total_time = time.time() - start_time
        results['actual_duration'] = total_time
        results['requests_per_minute'] = (results['requests_sent'] / total_time) * 60 if total_time > 0 else 0
        results['end_time'] = datetime.now().isoformat()

        # Calculate average response time
        if results['response_times']:
            results['avg_response_time'] = sum(results['response_times']) / len(results['response_times'])
            results['min_response_time'] = min(results['response_times'])
            results['max_response_time'] = max(results['response_times'])

        return results

    def _refresh_tokens(self, user: User) -> bool:
        """
        Refresh authentication tokens for a specific user by calling the refresh endpoint.
        Based on TMSClient._refresh_tokens() pattern.

        Args:
            user: The User object whose tokens need refreshing

        Returns:
            True if refresh was successful, False otherwise
        """
        if not self.refresh_endpoint:
            return False

        try:
            self.logger.debug(f"   [{user.name}] Calling refresh endpoint: {self.refresh_endpoint}")

            # Make refresh request with user's session
            response = user.session.post(self.refresh_endpoint, timeout=10)
            response.encoding = 'utf-8'

            if response.status_code == 200:
                self.logger.info(f"   [{user.name}] Token refresh successful (status: {response.status_code})")

                # Update cookies from response
                new_cookies = {}
                for cookie in response.cookies:
                    new_cookies[cookie.name] = cookie.value
                    # Update session cookies
                    user.session.cookies.set(cookie.name, cookie.value)
                    self.logger.debug(f"   [{user.name}] Updated cookie: {cookie.name}={cookie.value[:20]}...")

                return True
            else:
                self.logger.error(f"   [{user.name}] Token refresh failed: {response.status_code} {response.reason}")
                return False

        except Exception as e:
            self.logger.error(f"   [{user.name}] Error during token refresh: {str(e)}")
            return False

    @staticmethod
    def print_results(results: Dict):
        """Print formatted test results."""
        print(f"\n{'='*70}")
        print("RATE LIMIT TEST RESULTS")
        print(f"{'='*70}")
        print(f"URL: {results['url']}")
        print(f"Test Duration: {results['actual_duration']:.2f} seconds")
        print(f"Users: {results['num_users']} (rotation every {results['requests_per_user_rotation']} request(s))")
        print(f"\nRequests:")
        print(f"  Total Sent:     {results['requests_sent']}")
        print(f"  Successful:     {results['successful_requests']} "
              f"({results['successful_requests']/results['requests_sent']*100:.1f}%)")
        print(f"  Failed:         {results['failed_requests']}")
        print(f"  Rate Limited:   {results['rate_limited_requests']}")
        print(f"\nPerformance:")
        print(f"  Requests/Minute: {results['requests_per_minute']:.2f}")

        if results['response_times']:
            print(f"  Avg Response:   {results['avg_response_time']:.3f}s")
            print(f"  Min Response:   {results['min_response_time']:.3f}s")
            print(f"  Max Response:   {results['max_response_time']:.3f}s")

        print(f"\nStatus Codes:")
        for code, count in sorted(results['status_codes'].items()):
            print(f"  {code}: {count} requests")

        print(f"\nPer-User Statistics:")
        for user_name, stats in results['user_stats'].items():
            print(f"  {user_name}:")
            print(f"    Requests:     {stats['requests']}")
            print(f"    Successful:   {stats['successful']}")
            print(f"    Failed:       {stats['failed']}")
            print(f"    Rate Limited: {stats['rate_limited']}")

        if results['rate_limit_detected_at']:
            print(f"\nRate Limit Info:")
            print(f"  First detected at request #{results['rate_limit_detected_at']}")
            print(f"  Approximately {results['rate_limit_detected_at']} requests allowed")

        if results['errors']:
            print(f"\nErrors: {len(results['errors'])} occurred")
            for error in results['errors'][:5]:  # Show first 5
                print(f"  Request #{error['request_number']}: {error['error']}")

        print(f"{'='*70}\n")

    @staticmethod
    def save_results(results: Dict, output_file: str):
        """Save results to JSON file."""
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Results saved to: {output_path}")


def parse_headers_from_file(headers_file: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Parse HTTP headers from a file.

    Returns:
        Tuple of (headers_dict, cookies_dict)
    """
    headers = {}
    cookies = {}

    with open(headers_file, 'r') as f:
        content = f.read()

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(('GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HTTP/')):
            continue

        parts = line.split(': ', 1)
        if len(parts) != 2:
            continue

        key, value = parts
        if key.lower() == 'cookie':
            # Parse cookies
            for cookie in value.split('; '):
                if '=' in cookie:
                    cookie_name, cookie_value = cookie.split('=', 1)
                    cookies[cookie_name] = cookie_value
        else:
            headers[key] = value

    return headers, cookies


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Test rate limits on HTTP endpoints with multiple user support'
    )
    parser.add_argument(
        'url',
        help='URL to test (or use --user-files to extract URL)'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Test duration in seconds (default: 60)'
    )
    parser.add_argument(
        '--max-requests',
        type=int,
        default=1000,
        help='Maximum number of requests (default: 1000)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.0,
        help='Delay between requests in seconds (default: 0)'
    )
    parser.add_argument(
        '--method',
        default='GET',
        choices=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'],
        help='HTTP method (default: GET)'
    )
    parser.add_argument(
        '--user-files',
        nargs='+',
        help='Files containing HTTP headers for each user (e.g., user1.txt user2.txt)'
    )
    parser.add_argument(
        '--headers-file',
        help='Single file containing HTTP headers (legacy, use --user-files instead)'
    )
    parser.add_argument(
        '--requests-per-user',
        type=int,
        default=10,
        help='Number of requests per user before rotating (default: 10 for round-robin)'
    )
    parser.add_argument(
        '--output',
        help='Save results to JSON file'
    )
    parser.add_argument(
        '--refresh-endpoint',
        help='Token refresh endpoint URL (auto-detected for TMS API)'
    )
    parser.add_argument(
        '--no-auto-refresh',
        action='store_true',
        help='Disable automatic token refresh on 401 errors'
    )
    parser.add_argument(
        '--log-file',
        help='Save detailed logs with millisecond precision to file'
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO). Use DEBUG for per-request ms logging'
    )

    args = parser.parse_args()

    # Setup logger
    logger = setup_logger(log_file=args.log_file)
    logger.setLevel(getattr(logging, args.log_level))

    # Also set the level for all handlers
    for handler in logger.handlers:
        handler.setLevel(getattr(logging, args.log_level))

    url = args.url
    refresh_endpoint = args.refresh_endpoint
    users = []

    # Determine which files to use
    user_files = args.user_files or ([args.headers_file] if args.headers_file else [])

    if not user_files:
        logger.error("Error: Must provide at least one user file using --user-files or --headers-file")
        return

    # Parse each user file
    for idx, user_file in enumerate(user_files):
        headers, cookies = parse_headers_from_file(user_file)

        # Extract URL from first line if it's an HTTP request (only from first file)
        if idx == 0:
            with open(user_file, 'r') as f:
                first_line = f.readline().strip()
                if first_line.startswith(('GET', 'POST', 'PUT', 'DELETE', 'PATCH')):
                    parts = first_line.split()
                    if len(parts) >= 2:
                        path = parts[1]
                        # Try to construct full URL from Host header
                        if 'Host' in headers:
                            protocol = 'https' if cookies or 'XSRF-TOKEN' in cookies else 'http'
                            url = f"{protocol}://{headers['Host']}{path}"
                            logger.info(f"Extracted URL: {url}")

                            # Auto-detect TMS refresh endpoint if not specified
                            if not refresh_endpoint and 'nepsetms.com.np' in headers.get('Host', ''):
                                refresh_endpoint = f"{protocol}://{headers['Host']}/tmsapi/authApi/authenticate/refresh"
                                logger.info(f"Auto-detected refresh endpoint: {refresh_endpoint}")

        # Create user with a name based on file
        user_name = f"User{idx+1}"
        user = User(name=user_name, headers=headers, cookies=cookies)
        users.append(user)
        logger.info(f"Loaded {user_name} from {user_file}")

    # Initialize tester
    tester = RateLimitTester(
        url=url,
        users=users,
        refresh_endpoint=refresh_endpoint,
        auto_refresh_on_401=not args.no_auto_refresh,
        requests_per_user=args.requests_per_user,
        logger=logger
    )

    # Run test
    results = tester.test_rate_limit(
        duration_seconds=args.duration,
        max_requests=args.max_requests,
        delay_between_requests=args.delay,
        method=args.method
    )

    # Print results
    tester.print_results(results)

    # Save results if output file specified
    if args.output:
        tester.save_results(results, args.output)
        logger.info(f"Results saved to: {args.output}")

    # Log summary of request timing coverage if detailed logging was enabled
    if args.log_level == 'DEBUG' and results['request_log']:
        logger.info("\nTiming Coverage Analysis:")
        for i in range(min(5, len(results['request_log']) - 1)):
            curr = results['request_log'][i]
            next_req = results['request_log'][i + 1]
            gap_ms = next_req['timestamp_start_ms'] - curr['timestamp_end_ms']
            logger.info(f"  Gap between request #{curr['request_number']} and #{next_req['request_number']}: {gap_ms}ms")


if __name__ == '__main__':
    main()
