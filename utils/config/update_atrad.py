import json
import argparse
from pathlib import Path

from utils.config.atrad_config_actions import (
    ALLOWED_DEFAULT_KEYS,
    reset_atrad_jsession_ids,
    set_atrad_numeric_key,
)

# Allowed keys that can be set via --set flag
ALLOWED_KEYS = ALLOWED_DEFAULT_KEYS


def reset_tokens():
    """
    Reset JSESSIONID tokens in all atrad_user*.json files by setting them to empty string.
    Only modifies the JSESSIONID field, leaving all other data unchanged.
    """
    users_dir = Path(__file__).resolve().parents[2] / "users"
    results = reset_atrad_jsession_ids(users_dir)
    if not results:
        print("No atrad_user*.json files found")
        return

    print(f"Found {len(results)} user files")
    for result in results:
        print(f"{result.details} in {result.path.name}")

    print("\nToken reset complete!")


def set_config(key, value):
    """
    Set a configuration value in all atrad_user*.json files.
    Only allowed to set specific keys defined in ALLOWED_KEYS.

    Args:
        key: The configuration key to set
        value: The value to set (will be converted to appropriate type)
    """
    if key not in ALLOWED_KEYS:
        print(f"✗ Error: Key '{key}' is not allowed.")
        print(f"Allowed keys: {', '.join(sorted(ALLOWED_KEYS))}")
        return

    try:
        results = set_atrad_numeric_key(
            key,
            value,
            Path(__file__).resolve().parents[2] / "users",
        )
    except ValueError as exc:
        print(f"✗ Error: {exc}")
        return

    if not results:
        print("No atrad_user*.json files found")
        return

    print(f"Found {len(results)} user files")
    for result in results:
        print(f"Updated {result.path.name}: {result.details}")

    print(f"\nConfiguration update complete!")


def main():
    parser = argparse.ArgumentParser(
        description='Update atrad_user*.json configuration files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Reset JSESSIONID tokens
  python utils/update_atrad.py --reset

  # Set a configuration value
  python utils/update_atrad.py --set trigger_mode_poll_interval_ms 50

Allowed keys for --set:
  {chr(10).join('  - ' + key for key in sorted(ALLOWED_KEYS))}
"""
    )

    parser.add_argument('--reset', action='store_true',
                        help='Reset JSESSIONID to empty string in all atrad_user*.json files')
    parser.add_argument('--set', nargs=2, metavar=('KEY', 'VALUE'),
                        help='Set a configuration value (key value)')

    args = parser.parse_args()

    # Check if any action was specified
    if not args.reset and not args.set:
        parser.print_help()
        return

    # Execute requested action(s)
    if args.reset:
        reset_tokens()

    if args.set:
        key, value = args.set
        print()  # Add spacing if both flags are used
        set_config(key, value)


if __name__ == "__main__":
    main()
