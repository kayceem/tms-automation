import json
import glob
import argparse
from pathlib import Path


# Allowed keys that can be set via --set flag
ALLOWED_KEYS = {
    'trigger_mode_poll_interval_ms',
    'trigger_mode_refresh_interval_seconds',
    'trigger_sell_poll_interval_ms',
    'trigger_mode_slow_poll_interval_ms',
    'trigger_mode_requests_per_fetch_user'
}


def reset_tokens():
    """
    Reset JSESSIONID tokens in all atrad_user*.json files by setting them to empty string.
    Only modifies the JSESSIONID field, leaving all other data unchanged.
    """
    # Get the project root directory (parent of utils)
    project_root = Path(__file__).parent.parent.parent
    users_dir = project_root / "users"

    # Find all atrad_user*.json files
    user_files = glob.glob(str(users_dir / "atrad_user*.json"))

    if not user_files:
        print("No atrad_user*.json files found")
        return

    print(f"Found {len(user_files)} user files")

    for user_file in user_files:
        try:
            # Read the user file
            with open(user_file, 'r') as f:
                user_data = json.load(f)

            # Check if _cookies and JSESSIONID exist
            if '_cookies' in user_data and 'JSESSIONID' in user_data['_cookies']:
                # Reset JSESSIONID to empty string
                user_data['_cookies']['JSESSIONID'] = ""

                # Write back to file with proper formatting
                with open(user_file, 'w') as f:
                    json.dump(user_data, f, indent=2)

                print(f"Reset JSESSIONID in {Path(user_file).name}")
            else:
                print(f"No JSESSIONID found in {Path(user_file).name}")

        except Exception as e:
            print(f"✗ Error processing {Path(user_file).name}: {str(e)}")

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

    # Get the project root directory (parent of utils)
    project_root = Path(__file__).parent.parent
    users_dir = project_root / "users"

    # Find all atrad_user*.json files
    user_files = glob.glob(str(users_dir / "atrad_user*.json"))

    if not user_files:
        print("No atrad_user*.json files found")
        return

    print(f"Found {len(user_files)} user files")

    # Convert value to appropriate type (all current allowed keys use numeric values)
    try:
        # Try to convert to int first, then float if that fails
        try:
            converted_value = int(value)
        except ValueError:
            converted_value = float(value)
    except ValueError:
        print(f"✗ Error: Value '{value}' is not a valid number")
        return

    for user_file in user_files:
        try:
            # Read the user file
            with open(user_file, 'r') as f:
                user_data = json.load(f)

            # Set the key-value pair
            old_value = user_data.get(key, "not set")
            user_data[key] = converted_value

            # Write back to file with proper formatting
            with open(user_file, 'w') as f:
                json.dump(user_data, f, indent=2)

            print(f"Updated {Path(user_file).name}: {key} = {converted_value} (was: {old_value})")

        except Exception as e:
            print(f"✗ Error processing {Path(user_file).name}: {str(e)}")

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
