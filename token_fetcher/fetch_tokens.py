#!/usr/bin/env python3
"""
Token Fetcher CLI Script

Usage:
    python fetch_tokens.py --user 1                    # Fetch token for user 1
    python fetch_tokens.py --all --count 5              # Fetch tokens for users 1-5
    python fetch_tokens.py --user 2 --headless          # Run in headless mode
"""

import argparse
import sys
from token_fetcher import TokenFetcher


def main():
    parser = argparse.ArgumentParser(
        description='Fetch authentication tokens for users',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Fetch token for a single user:
    python fetch_tokens.py --user 1

  Fetch tokens for multiple users:
    python fetch_tokens.py --all --count 5

  Run in headless mode:
    python fetch_tokens.py --user 1 --headless

  Specify retry attempts:
    python fetch_tokens.py --user 1 --retries 5
        """
    )

    parser.add_argument(
        '--user',
        type=int,
        help='User number to fetch token for (e.g., 1 for user_cred1.json)'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Fetch tokens for all users'
    )

    parser.add_argument(
        '--count',
        type=int,
        default=10,
        help='Number of users to process when using --all (default: 6)'
    )

    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run browser in headless mode (no GUI)'
    )

    parser.add_argument(
        '--retries',
        type=int,
        default=3,
        help='Maximum number of login retry attempts (default: 3)'
    )

    parser.add_argument(
        '--manual-captcha',
        action='store_true',
        help='Manually enter captcha instead of using OCR'
    )

    parser.add_argument(
        '--debug-images',
        action='store_true',
        help='Save captcha images for debugging OCR issues'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.user and not args.all:
        parser.error('Either --user or --all must be specified')

    if args.user and args.all:
        parser.error('Cannot specify both --user and --all')

    # Create token fetcher instance
    fetcher = TokenFetcher(
        headless=args.headless,
        manual_captcha=args.manual_captcha,
        debug_images=args.debug_images
    )

    try:
        if args.all:
            # Fetch tokens for all users
            print(f"Fetching tokens for {args.count} users...")
            results = fetcher.fetch_all_users(args.count)

            # Print summary
            print("\n" + "="*50)
            print("SUMMARY")
            print("="*50)

            success_count = sum(1 for r in results.values() if r.get('success'))
            fail_count = len(results) - success_count

            print(f"Total users: {len(results)}")
            print(f"Success: {success_count}")
            print(f"Failed: {fail_count}")

            if fail_count > 0:
                print("\nFailed users:")
                for user, result in results.items():
                    if not result.get('success'):
                        print(f"  - {user}: {result.get('error', 'Unknown error')}")

        else:
            # Fetch token for single user
            print(f"Fetching token for user {args.user}...")
            result = fetcher.fetch_token(args.user, max_retries=args.retries)

            if result['success']:
                print(f"\n✓ Successfully fetched token for user {args.user}")
                print(f"Cookies: {result.get('cookies', {}).keys()}")
            else:
                print(f"\n✗ Failed to fetch token for user {args.user}")
                print(f"Error: {result.get('error', 'Unknown error')}")
                sys.exit(1)

    except FileNotFoundError as e:
        print(f"\nError: {e}")
        print(f"\nMake sure user credentials file exists in token_fetcher/users/ directory")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
