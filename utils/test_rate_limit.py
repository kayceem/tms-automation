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


class RateLimitTester:
    """Test rate limits for HTTP endpoints."""

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None,
                 cookies: Optional[Dict[str, str]] = None,
                 refresh_endpoint: Optional[str] = None,
                 auto_refresh_on_401: bool = True):
        """
        Initialize rate limit tester.

        Args:
            url: The endpoint URL to test
            headers: Optional request headers
            cookies: Optional cookies
            refresh_endpoint: Optional token refresh endpoint URL
            auto_refresh_on_401: Automatically refresh tokens on 401 errors (default: True)
        """
        self.url = url
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.refresh_endpoint = refresh_endpoint
        self.auto_refresh_on_401 = auto_refresh_on_401
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        if self.cookies:
            for key, value in self.cookies.items():
                self.session.cookies.set(key, value)

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
            'requests_sent': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'rate_limited_requests': 0,
            'status_codes': defaultdict(int),
            'response_times': [],
            'errors': [],
            'rate_limit_detected_at': None,
            'requests_per_minute': 0
        }

        start_time = time.time()
        end_time = start_time + duration_seconds
        first_rate_limit = None

        print(f"\n{'='*70}")
        print(f"Starting rate limit test for: {self.url}")
        print(f"Duration: {duration_seconds} seconds")
        print(f"Max requests: {max_requests}")
        print(f"Method: {method}")
        print(f"{'='*70}\n")

        request_count = 0

        try:
            while time.time() < end_time and request_count < max_requests:
                request_count += 1
                request_start = time.time()

                try:
                    # Make request
                    if method.upper() == "POST":
                        response = self.session.post(self.url, json=payload, timeout=10)
                    elif method.upper() == "GET":
                        response = self.session.get(self.url, timeout=10)
                    else:
                        response = self.session.request(method, self.url, json=payload, timeout=10)

                    request_time = time.time() - request_start
                    results['response_times'].append(request_time)
                    results['requests_sent'] += 1

                    # Handle 401 with automatic token refresh
                    if response.status_code == 401 and self.auto_refresh_on_401 and self.refresh_endpoint:
                        print(f"\n🔄 Session expired at request #{request_count}, attempting token refresh...")
                        if self._refresh_tokens():
                            print(f"✓ Tokens refreshed successfully, retrying request #{request_count}")
                            # Retry the request with new tokens
                            retry_start = time.time()
                            if method.upper() == "POST":
                                response = self.session.post(self.url, json=payload, timeout=10)
                            elif method.upper() == "GET":
                                response = self.session.get(self.url, timeout=10)
                            else:
                                response = self.session.request(method, self.url, json=payload, timeout=10)
                            request_time = time.time() - retry_start
                        else:
                            print(f"✗ Token refresh failed")

                    # Track status code
                    results['status_codes'][response.status_code] += 1

                    # Check for rate limiting
                    if response.status_code == 429:  # Too Many Requests
                        results['rate_limited_requests'] += 1
                        if first_rate_limit is None:
                            first_rate_limit = request_count
                            results['rate_limit_detected_at'] = request_count
                            print(f"\nRATE LIMIT DETECTED at request #{request_count}")
                            print(f"   Response: {response.status_code} {response.reason}")
                            if 'Retry-After' in response.headers:
                                print(f"   Retry-After: {response.headers['Retry-After']}s")

                    # Check for other error status codes that might indicate rate limiting
                    elif response.status_code in [503, 509, 403]:
                        results['failed_requests'] += 1
                        if first_rate_limit is None:
                            # Could be rate limiting with different status code
                            print(f"\nPossible rate limit at request #{request_count}")
                            print(f"   Response: {response.status_code} {response.reason}")
                    elif response.status_code >= 400:
                        results['failed_requests'] += 1
                    else:
                        results['successful_requests'] += 1

                    # Print progress every 10 requests
                    if request_count % 10 == 0:
                        elapsed = time.time() - start_time
                        rpm = (request_count / elapsed) * 60 if elapsed > 0 else 0
                        print(f"Request #{request_count:4d} | "
                              f"Status: {response.status_code} | "
                              f"Time: {request_time:.3f}s | "
                              f"Rate: {rpm:.1f} req/min")

                except requests.Timeout:
                    results['errors'].append({
                        'request_number': request_count,
                        'error': 'Timeout',
                        'time': time.time() - start_time
                    })
                    print(f"Request #{request_count:4d} | TIMEOUT")

                except requests.RequestException as e:
                    results['errors'].append({
                        'request_number': request_count,
                        'error': str(e),
                        'time': time.time() - start_time
                    })
                    print(f"Request #{request_count:4d} | ERROR: {str(e)}")

                # Delay between requests if specified
                if delay_between_requests > 0:
                    time.sleep(delay_between_requests)
                if request_count % 10 == 0:
                    print(f"Sleeping for {delay_between_requests}s between requests...")
                    time.sleep(2)

        except KeyboardInterrupt:
            print("\n\nTest interrupted by user")

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

    def _refresh_tokens(self) -> bool:
        """
        Refresh authentication tokens by calling the refresh endpoint.
        Based on TMSClient._refresh_tokens() pattern.

        Returns:
            True if refresh was successful, False otherwise
        """
        if not self.refresh_endpoint:
            return False

        try:
            print(f"   Calling refresh endpoint: {self.refresh_endpoint}")

            # Make refresh request
            response = self.session.post(self.refresh_endpoint, timeout=10)
            response.encoding = 'utf-8'

            if response.status_code == 200:
                print(f"   ✓ Token refresh successful (status: {response.status_code})")

                # Update cookies from response
                new_cookies = {}
                for cookie in response.cookies:
                    new_cookies[cookie.name] = cookie.value
                    # Update session cookies
                    self.session.cookies.set(cookie.name, cookie.value)
                    print(f"   Updated cookie: {cookie.name}={cookie.value[:20]}...")

                return True
            else:
                print(f"   ✗ Token refresh failed: {response.status_code} {response.reason}")
                return False

        except Exception as e:
            print(f"   ✗ Error during token refresh: {str(e)}")
            return False

    @staticmethod
    def print_results(results: Dict):
        """Print formatted test results."""
        print(f"\n{'='*70}")
        print("RATE LIMIT TEST RESULTS")
        print(f"{'='*70}")
        print(f"URL: {results['url']}")
        print(f"Test Duration: {results['actual_duration']:.2f} seconds")
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
        description='Test rate limits on HTTP endpoints'
    )
    parser.add_argument(
        'url',
        help='URL to test (or use --headers-file to extract URL)'
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
        '--headers-file',
        help='File containing HTTP headers (like test.txt)'
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

    args = parser.parse_args()

    headers = {}
    cookies = {}
    url = args.url
    refresh_endpoint = args.refresh_endpoint

    # Parse headers file if provided
    if args.headers_file:
        headers, cookies = parse_headers_from_file(args.headers_file)

        # Extract URL from first line if it's an HTTP request
        with open(args.headers_file, 'r') as f:
            first_line = f.readline().strip()
            if first_line.startswith(('GET', 'POST', 'PUT', 'DELETE', 'PATCH')):
                parts = first_line.split()
                if len(parts) >= 2:
                    path = parts[1]
                    # Try to construct full URL from Host header
                    if 'Host' in headers:
                        protocol = 'https' if cookies or 'XSRF-TOKEN' in cookies else 'http'
                        url = f"{protocol}://{headers['Host']}{path}"
                        print(f"Extracted URL: {url}")

                        # Auto-detect TMS refresh endpoint if not specified
                        if not refresh_endpoint and 'nepsetms.com.np' in headers.get('Host', ''):
                            refresh_endpoint = f"{protocol}://{headers['Host']}/tmsapi/authApi/authenticate/refresh"
                            print(f"Auto-detected refresh endpoint: {refresh_endpoint}")

    # Initialize tester
    tester = RateLimitTester(
        url=url,
        headers=headers,
        cookies=cookies,
        refresh_endpoint=refresh_endpoint,
        auto_refresh_on_401=not args.no_auto_refresh
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


if __name__ == '__main__':
    main()
