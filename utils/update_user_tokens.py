#!/usr/bin/env python3
"""
Script to extract tokens and session IDs from HTTP request headers
and update the user.json file based on user_id.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, Optional


def extract_from_headers(headers_text: str) -> Dict[str, str]:
    """
    Extract relevant tokens and IDs from HTTP request headers.

    Args:
        headers_text: Raw HTTP request headers as a string

    Returns:
        Dictionary containing extracted values
    """
    extracted = {}
    lines = headers_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(": ", 1)
        if len(parts) < 2:
            continue
        if parts[0] == "Request-Owner":
            extracted['request_owner'] = parts[1].strip()
        elif parts[0] == "Host-Session-Id":
            extracted['host_session_id'] = parts[1].strip()
        elif parts[0] == "X-XSRF-TOKEN":
            extracted['xsrf_token'] = parts[1].strip()
        elif parts[0] == "Cookie":
            cookie_parts = parts[1].split("; ")
            for cookie in cookie_parts:
                if cookie.startswith("_rid="):
                    extracted['rid_cookie'] = cookie.split("=", 1)[1].strip()
                elif cookie.startswith("_aid="):
                    extracted['access_token'] = cookie.split("=", 1)[1].strip()

    return extracted


def update_user_json(user_id: str, extracted_data: Dict[str, str], user_json_path: Optional[str] = None) -> bool:
    """
    Update the user.json file with extracted tokens and IDs.

    Args:
        user_id: The user_id to match in the JSON file
        extracted_data: Dictionary containing the extracted tokens and IDs
        user_json_path: Path to user.json file (defaults to users/user.json)

    Returns:
        True if update was successful, False otherwise
    """
    if user_json_path is None:
        # Default path relative to script location
        script_dir = Path(__file__).parent.parent
        user_json_path = script_dir / 'users' / 'user.json'
    else:
        user_json_path = Path(user_json_path)

    if not user_json_path.exists():
        print(f"Error: User JSON file not found at {user_json_path}")
        return False

    try:
        # Read existing user data
        with open(user_json_path, 'r') as f:
            user_data = json.load(f)

        # Check if the user_id matches
        if user_data.get('user_id') != user_id:
            print(f"Error: user_id '{user_id}' does not match the user_id in {user_json_path}")
            print(f"       Found user_id: '{user_data.get('user_id')}'")
            return False

        # Update the fields
        updated_fields = []
        for key, value in extracted_data.items():
            if value:  # Only update if we have a value
                user_data[key] = value
                updated_fields.append(key)

        # Write updated data back to file
        with open(user_json_path, 'w') as f:
            json.dump(user_data, f, indent=2)

        print(f"✓ Successfully updated user.json for user_id: {user_id}")
        print(f"  Updated fields: {', '.join(updated_fields)}")
        return True

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {user_json_path}: {e}")
        return False
    except Exception as e:
        print(f"Error updating user.json: {e}")
        return False


def main():
    """Main function to run the script interactively or with file input."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Extract tokens from HTTP headers and update user.json'
    )
    parser.add_argument(
        '--user-id',
        required=True,
        help='User ID to match in user.json'
    )
    parser.add_argument(
        '--headers-file',
        help='Path to file containing HTTP request headers'
    )
    parser.add_argument(
        '--user-json',
        help='Path to user.json file (defaults to users/user.json)'
    )

    args = parser.parse_args()

    # Get headers text
    if args.headers_file:
        with open(args.headers_file, 'r') as f:
            headers_text = f.read()
    else:
        print("Paste your HTTP request headers (press Ctrl+D when done):")
        print("-" * 60)
        import sys
        headers_text = sys.stdin.read()

    # Extract tokens and IDs
    extracted_data = extract_from_headers(headers_text)

    if not extracted_data:
        print("Warning: No tokens or IDs found in the headers")
        return

    print("\nExtracted data:")
    for key, value in extracted_data.items():
        # Show only first 40 chars for security
        display_value = value[:40] + "..." if len(value) > 40 else value
        print(f"  {key}: {display_value}")

    # Update user.json
    print()
    update_user_json(args.user_id, extracted_data, args.user_json)


if __name__ == '__main__':
    main()
