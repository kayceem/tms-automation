"""
Rate Limit Optimizer - Find optimal wait times for order placement.

This script tests different wait time configurations to maximize time coverage
while maintaining acceptable success rates (avoiding 400 errors).
"""

import json
import time
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
import sys

# Add parent directory to path to import project modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.tms_client import TMSClient
from config.user_config import UserConfig


@dataclass
class TestResult:
    """Results from a single wait time configuration test.

    Note: successful_orders includes actual orders PLUS 400/401 errors.
    This is because 400 (rate limit) and 401 (auth) errors still count as
    valid coverage attempts - they consume time but the attempt was made.
    Only 502 and other errors are considered actual failures.
    """
    wait_time: float
    test_duration_seconds: int
    total_attempts: int
    successful_orders: int  # Includes actual orders + 400/401 (coverage attempts)
    error_400_count: int    # Rate limit - counts as coverage (wasted time)
    error_401_count: int    # Auth issue - counts as coverage (wasted time)
    error_502_count: int    # Server error - actual failure
    other_errors: int       # Other errors - actual failures
    success_rate: float     # (actual_orders + 400/401) / total_attempts
    time_coverage: float    # Percentage of seconds covered
    avg_response_time: float
    avg_time_between_good_orders: float  # Avg seconds between good orders (200/400/401)
    good_orders_per_minute: float  # Good orders (200/400/401) per minute
    unique_seconds_covered: int
    score: float  # Weighted score: success_rate * coverage


@dataclass
class TestConfig:
    """Configuration for rate limit testing."""
    wait_times: List[float]
    test_duration_minutes: int
    security_id: int
    exchange_security_id: int
    order_price: float
    order_quantity: int
    buy_or_sell: int
    min_success_rate: float  # Minimum acceptable success rate (e.g., 0.95)


class RateLimitOptimizer:
    """Test different wait times to find optimal configuration."""

    def __init__(self, user_config_path: str, test_config: TestConfig):
        """
        Initialize the optimizer.

        Args:
            user_config_path: Path to user configuration JSON
            test_config: Test configuration parameters
        """
        self.user_config = UserConfig.from_file(user_config_path)
        self.client = TMSClient(self.user_config)
        self.test_config = test_config
        self.results: List[TestResult] = []

    def test_wait_time(self, wait_time: float) -> TestResult:
        """
        Test a specific wait time configuration.

        Args:
            wait_time: Time to wait between requests in seconds

        Returns:
            TestResult with metrics
        """
        print(f"\n{'='*70}")
        print(f"Testing wait time: {wait_time}s")
        print(f"{'='*70}")

        test_duration_seconds = self.test_config.test_duration_minutes * 60
        end_time = datetime.now() + timedelta(seconds=test_duration_seconds)

        # Metrics
        total_attempts = 0
        successful_orders = 0
        error_400_count = 0  # Rate limit - counts as valid attempt (coverage)
        error_401_count = 0  # Auth issue - counts as valid attempt (coverage)
        error_502_count = 0  # Server error - counts as failure
        other_errors = 0     # Other errors - count as failures
        response_times = []
        seconds_with_attempts = set()
        good_order_timestamps = []  # Track timestamps of good orders (200/400/401)

        # Get client data
        client_data = self.user_config.client_data
        if not client_data:
            raise ValueError("Client data must be configured in user config")

        print(f"Test will run for {self.test_config.test_duration_minutes} minutes")
        print(f"Starting at: {datetime.now().strftime('%H:%M:%S')}")
        print(f"Ending at: {end_time.strftime('%H:%M:%S')}")
        print(f"Target: {self.test_config.security_id}, Price: Rs. {self.test_config.order_price}")

        while datetime.now() < end_time:
            total_attempts += 1
            current_second = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            seconds_with_attempts.add(current_second)

            try:
                # Time the request
                start_time = time.time()

                response = self.client.place_order(
                    security_id=self.test_config.security_id,
                    exchange_security_id=self.test_config.exchange_security_id,
                    order_price=self.test_config.order_price,
                    order_quantity=self.test_config.order_quantity,
                    client_data=client_data,
                    buy_or_sell=self.test_config.buy_or_sell
                )

                response_time = time.time() - start_time
                response_times.append(response_time)

                if response:
                    successful_orders += 1
                    good_order_timestamps.append(time.time())  # Track good order time
                    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    print(f"[{total_attempts:4d}] {timestamp} SUCCESS (response: {response_time:.3f}s)")

                # Wait before next attempt
                time.sleep(wait_time)

            except KeyboardInterrupt:
                print("\n\nTest interrupted by user!")
                break

            except Exception as e:
                error_msg = str(e)
                timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]

                # Categorize errors
                # 400 and 401 are "expected" - they count toward coverage but not failures
                if "400" in error_msg or "Bad Request" in error_msg:
                    error_400_count += 1
                    successful_orders += 1  # Count as "successful coverage attempt"
                    good_order_timestamps.append(time.time())  # Track good order time
                    print(f"[{total_attempts:4d}] {timestamp} ERROR 400 (rate limit - coverage OK)")
                elif "401" in error_msg or "Unauthorized" in error_msg:
                    error_401_count += 1
                    successful_orders += 1  # Count as "successful coverage attempt"
                    good_order_timestamps.append(time.time())  # Track good order time
                    print(f"[{total_attempts:4d}] {timestamp} ERROR 401 (auth - coverage OK)")
                # 502 and other errors are actual failures
                elif "502" in error_msg or "Bad Gateway" in error_msg:
                    error_502_count += 1
                    print(f"[{total_attempts:4d}] {timestamp} ERROR 502 (gateway - FAILURE)")
                else:
                    other_errors += 1
                    print(f"[{total_attempts:4d}] {timestamp} ERROR: {error_msg[:50]} - FAILURE")

                # Wait before retry
                time.sleep(wait_time)

        # Calculate metrics
        # Success rate = (successful orders + 400/401 errors) / total attempts
        # 400/401 already counted in successful_orders above
        success_rate = successful_orders / total_attempts if total_attempts > 0 else 0
        unique_seconds_covered = len(seconds_with_attempts)
        time_coverage = (unique_seconds_covered / test_duration_seconds) * 100
        avg_response_time = statistics.mean(response_times) if response_times else 0

        # Calculate time between good orders (200/400/401)
        if len(good_order_timestamps) >= 2:
            time_gaps = [good_order_timestamps[i] - good_order_timestamps[i-1]
                        for i in range(1, len(good_order_timestamps))]
            avg_time_between_good_orders = statistics.mean(time_gaps)
        elif len(good_order_timestamps) == 1:
            avg_time_between_good_orders = test_duration_seconds  # Only one order
        else:
            avg_time_between_good_orders = float('inf')  # No good orders

        # Good orders per minute
        good_orders_per_minute = (successful_orders / test_duration_seconds) * 60 if test_duration_seconds > 0 else 0

        # Score: weighted combination of success rate and coverage
        # Prioritize success rate but reward coverage
        score = (success_rate * 0.6) + (time_coverage / 100 * 0.4)

        result = TestResult(
            wait_time=wait_time,
            test_duration_seconds=test_duration_seconds,
            total_attempts=total_attempts,
            successful_orders=successful_orders,
            error_400_count=error_400_count,
            error_401_count=error_401_count,
            error_502_count=error_502_count,
            other_errors=other_errors,
            success_rate=success_rate,
            time_coverage=time_coverage,
            avg_response_time=avg_response_time,
            avg_time_between_good_orders=avg_time_between_good_orders,
            good_orders_per_minute=good_orders_per_minute,
            unique_seconds_covered=unique_seconds_covered,
            score=score
        )

        self._print_result_summary(result)
        return result

    def _print_result_summary(self, result: TestResult):
        """Print summary of test results."""
        actual_orders = result.successful_orders - result.error_400_count - result.error_401_count
        coverage_attempts = result.error_400_count + result.error_401_count
        actual_failures = result.error_502_count + result.other_errors

        print(f"\n{'-'*70}")
        print(f"RESULTS FOR WAIT TIME: {result.wait_time}s")
        print(f"{'-'*70}")
        print(f"Total Attempts:        {result.total_attempts}")
        print(f"  • Actual Orders:     {actual_orders} (successfully placed)")
        print(f"  • Coverage Only:     {coverage_attempts} (400/401 - time covered but no order)")
        print(f"  • Failed:            {actual_failures} (502/other - real failures)")
        print(f"Success Rate:          {result.success_rate*100:.2f}% (orders + coverage attempts)")
        print(f"Time Coverage:         {result.time_coverage:.2f}% ({result.unique_seconds_covered}/{result.test_duration_seconds} seconds)")
        print(f"Avg Response Time:     {result.avg_response_time:.3f}s")

        # Display good orders metrics
        if result.avg_time_between_good_orders == float('inf'):
            print(f"Avg Time Between Good Orders: N/A (no good orders)")
        else:
            print(f"Avg Time Between Good Orders: {result.avg_time_between_good_orders:.3f}s")
        print(f"Good Orders Per Minute: {result.good_orders_per_minute:.2f}")

        print(f"Weighted Score:        {result.score:.4f}")
        print(f"\nError Breakdown:")
        print(f"  400 (Rate Limit):    {result.error_400_count} - wasted time but coverage OK")
        print(f"  401 (Auth):          {result.error_401_count} - wasted time but coverage OK")
        print(f"  502 (Gateway):       {result.error_502_count} - ACTUAL FAILURE")
        print(f"  Other:               {result.other_errors} - ACTUAL FAILURE")
        print(f"{'-'*70}")

    def run_all_tests(self) -> List[TestResult]:
        """
        Run tests for all configured wait times.

        Returns:
            List of TestResults
        """
        print("\n" + "="*70)
        print("RATE LIMIT OPTIMIZATION TEST")
        print("="*70)
        print(f"User: {self.user_config.user_id}")
        print(f"Test Duration: {self.test_config.test_duration_minutes} minutes per wait time")
        print(f"Wait Times to Test: {self.test_config.wait_times}")
        print(f"Min Success Rate Target: {self.test_config.min_success_rate*100}%")
        print("="*70)

        for i, wait_time in enumerate(self.test_config.wait_times, 1):
            print(f"\n\nTest {i}/{len(self.test_config.wait_times)}")

            try:
                result = self.test_wait_time(wait_time)
                self.results.append(result)

                # Brief pause between tests
                if i < len(self.test_config.wait_times):
                    print(f"\nPausing 10 seconds before next test...")
                    time.sleep(10)

            except KeyboardInterrupt:
                print("\n\nAll tests interrupted by user!")
                break
            except Exception as e:
                print(f"\n\nERROR during test: {e}")
                import traceback
                traceback.print_exc()

        return self.results

    def analyze_results(self) -> Dict:
        """
        Analyze all results and recommend optimal configuration.

        Returns:
            Analysis dictionary with recommendations
        """
        if not self.results:
            return {"error": "No results to analyze"}

        print("\n\n" + "="*70)
        print("COMPREHENSIVE ANALYSIS")
        print("="*70)

        # Sort by score (descending)
        sorted_results = sorted(self.results, key=lambda x: x.score, reverse=True)

        # Find best overall
        best_overall = sorted_results[0]

        # Find best that meets minimum success rate
        best_meeting_threshold = None
        for result in sorted_results:
            if result.success_rate >= self.test_config.min_success_rate:
                best_meeting_threshold = result
                break

        # Print comparison table
        print("\nCOMPARISON TABLE")
        print("-"*70)
        print(f"{'Wait Time':<12} {'Success %':<12} {'Coverage %':<12} {'Score':<10} {'400 Errors':<12}")
        print("-"*70)

        for result in sorted(self.results, key=lambda x: x.wait_time):
            marker = " ★" if result == best_overall else ""
            threshold_marker = " ✓" if result.success_rate >= self.test_config.min_success_rate else " ✗"
            print(f"{result.wait_time:<12.2f} {result.success_rate*100:<12.2f} "
                  f"{result.time_coverage:<12.2f} {result.score:<10.4f} "
                  f"{result.error_400_count:<12}{threshold_marker}{marker}")

        print("-"*70)
        print("★ = Best overall score")
        print(f"✓ = Meets {self.test_config.min_success_rate*100}% success threshold")
        print(f"✗ = Below {self.test_config.min_success_rate*100}% success threshold")

        # Recommendations
        print("\n" + "="*70)
        print("RECOMMENDATIONS")
        print("="*70)

        print(f"\n1. BEST OVERALL (Highest Score):")
        print(f"   Wait Time: {best_overall.wait_time}s")
        print(f"   Success Rate: {best_overall.success_rate*100:.2f}%")
        print(f"   Time Coverage: {best_overall.time_coverage:.2f}%")
        print(f"   Score: {best_overall.score:.4f}")

        if best_meeting_threshold:
            print(f"\n2. BEST MEETING {self.test_config.min_success_rate*100}% SUCCESS THRESHOLD:")
            print(f"   Wait Time: {best_meeting_threshold.wait_time}s")
            print(f"   Success Rate: {best_meeting_threshold.success_rate*100:.2f}%")
            print(f"   Time Coverage: {best_meeting_threshold.time_coverage:.2f}%")
            print(f"   Score: {best_meeting_threshold.score:.4f}")
        else:
            print(f"\n2. WARNING: No configuration met {self.test_config.min_success_rate*100}% success threshold")
            print(f"   Consider testing higher wait times or reducing threshold")

        # Insights
        print("\n3. INSIGHTS:")

        # Coverage vs Success tradeoff
        fastest = min(self.results, key=lambda x: x.wait_time)
        slowest = max(self.results, key=lambda x: x.wait_time)

        print(f"   - Fastest wait time ({fastest.wait_time}s): "
              f"{fastest.success_rate*100:.1f}% success, {fastest.time_coverage:.1f}% coverage")
        print(f"   - Slowest wait time ({slowest.wait_time}s): "
              f"{slowest.success_rate*100:.1f}% success, {slowest.time_coverage:.1f}% coverage")

        # 400 error analysis
        total_400s = sum(r.error_400_count for r in self.results)
        if total_400s > 0:
            print(f"   - Total 400 errors across all tests: {total_400s}")
            most_400s = max(self.results, key=lambda x: x.error_400_count)
            print(f"   - Most 400 errors at {most_400s.wait_time}s wait time: {most_400s.error_400_count}")

        print("="*70)

        # Return structured analysis
        return {
            "best_overall": asdict(best_overall),
            "best_meeting_threshold": asdict(best_meeting_threshold) if best_meeting_threshold else None,
            "all_results": [asdict(r) for r in sorted_results],
            "summary": {
                "total_tests": len(self.results),
                "tests_meeting_threshold": sum(1 for r in self.results if r.success_rate >= self.test_config.min_success_rate),
                "fastest_wait": fastest.wait_time,
                "slowest_wait": slowest.wait_time
            }
        }

    def save_results(self, output_path: str):
        """
        Save results to JSON file.

        Args:
            output_path: Path to save JSON results
        """
        analysis = self.analyze_results()

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            json.dump(analysis, f, indent=2)

        print(f"\nResults saved to: {output_file}")


def main():
    """Main entry point for rate limit optimizer."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test different wait times to find optimal order placement rate"
    )
    parser.add_argument(
        "--user-config",
        required=True,
        help="Path to user configuration JSON file"
    )
    parser.add_argument(
        "--config",
        help="Path to test configuration JSON file (optional, can use CLI args instead)"
    )
    parser.add_argument(
        "--wait-times",
        nargs="+",
        type=float,
        help="List of wait times to test (e.g., 0.5 1.0 1.5 2.0 2.5)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=3,
        help="Test duration in minutes for each wait time (default: 3)"
    )
    parser.add_argument(
        "--security-id",
        type=int,
        help="Security ID to test with"
    )
    parser.add_argument(
        "--exchange-security-id",
        type=int,
        help="Exchange security ID to test with"
    )
    parser.add_argument(
        "--price",
        type=float,
        help="Order price"
    )
    parser.add_argument(
        "--quantity",
        type=int,
        default=10,
        help="Order quantity (default: 10)"
    )
    parser.add_argument(
        "--buy-or-sell",
        type=int,
        choices=[1, 2],
        default=1,
        help="1 for buy, 2 for sell (default: 1)"
    )
    parser.add_argument(
        "--min-success-rate",
        type=float,
        default=0.95,
        help="Minimum acceptable success rate (default: 0.95 = 95%%)"
    )
    parser.add_argument(
        "--output",
        default="tests/results/rate_limit_results.json",
        help="Output file for results (default: tests/results/rate_limit_results.json)"
    )

    args = parser.parse_args()

    # Load test config from file or CLI args
    if args.config:
        with open(args.config, 'r') as f:
            config_data = json.load(f)
        test_config = TestConfig(**config_data)
    else:
        # Build from CLI args
        if not all([args.wait_times, args.security_id, args.exchange_security_id, args.price]):
            parser.error("Must provide either --config file or all of: --wait-times, --security-id, --exchange-security-id, --price")

        test_config = TestConfig(
            wait_times=args.wait_times,
            test_duration_minutes=args.duration,
            security_id=args.security_id,
            exchange_security_id=args.exchange_security_id,
            order_price=args.price,
            order_quantity=args.quantity,
            buy_or_sell=args.buy_or_sell,
            min_success_rate=args.min_success_rate
        )

    # Create optimizer and run tests
    optimizer = RateLimitOptimizer(args.user_config, test_config)

    try:
        optimizer.run_all_tests()
        optimizer.save_results(args.output)

    except KeyboardInterrupt:
        print("\n\nTests interrupted! Analyzing partial results...")
        if optimizer.results:
            optimizer.save_results(args.output)
        else:
            print("No results to save.")

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
