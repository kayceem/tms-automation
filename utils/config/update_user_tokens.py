#!/usr/bin/env python3
"""
Script to extract tokens and session IDs from HTTP request headers
and update the user.json file based on user_id.
"""

import json
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
        script_dir = Path(__file__).parent.parent.parent
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
            print(f"Found user_id: '{user_data.get('user_id')}'")
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

        print(f"Successfully updated user.json for user_id: {user_id}")
        print(f"Updated fields: {', '.join(updated_fields)}")
        return True

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {user_json_path}: {e}")
        return False
    except Exception as e:
        print(f"Error updating user.json: {e}")
        return False


def process_auto_folder(folder_path: str) -> None:
    """
    Automatically process all headers{x}.txt files in a folder and update corresponding user{x}.json files.

    Args:
        folder_path: Path to the folder containing headers and user JSON files
    """
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        print(f"Error: Folder not found or is not a directory: {folder_path}")
        return

    # Find all headers{x}.txt files
    headers_files = sorted(folder.glob("headers*.txt"))

    if not headers_files:
        print(f"No headers*.txt files found in {folder_path}")
        return

    print(f"Found {len(headers_files)} headers file(s) in {folder_path}\n")

    success_count = 0
    failure_count = 0

    for headers_file in headers_files:
        # Extract the number/identifier from headers{x}.txt
        match = re.match(r'headers(.*)\.txt', headers_file.name)
        if not match:
            print(f"Skipping {headers_file.name}: unexpected filename format")
            continue

        identifier = match.group(1)
        user_json_file = folder / f"user{identifier}.json"

        print(f"Processing: {headers_file.name} → {user_json_file.name}")

        # Check if corresponding user JSON exists
        if not user_json_file.exists():
            print(f"Error: Corresponding user JSON not found: {user_json_file.name}\n")
            failure_count += 1
            continue

        try:
            # Read headers file
            with open(headers_file, 'r') as f:
                headers_text = f.read()

            # Extract tokens and IDs
            extracted_data = extract_from_headers(headers_text)

            if not extracted_data:
                print(f"Warning: No tokens or IDs found in {headers_file.name}\n")
                failure_count += 1
                continue

            # Read user JSON to get user_id
            with open(user_json_file, 'r') as f:
                user_data = json.load(f)

            user_id = user_data.get('user_id')
            if not user_id:
                print(f"Error: No user_id found in {user_json_file.name}\n")
                failure_count += 1
                continue

            # Update the user JSON
            if update_user_json(user_id, extracted_data, str(user_json_file)):
                success_count += 1
            else:
                failure_count += 1

            print()

        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {user_json_file.name}: {e}\n")
            failure_count += 1
        except Exception as e:
            print(f"Error processing {headers_file.name}: {e}\n")
            failure_count += 1

    # Summary
    print("=" * 60)
    print(f"Summary: {success_count} successful, {failure_count} failed")


def main():
    """Main function to run the script interactively or with file input."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Extract tokens from HTTP headers and update user.json'
    )
    parser.add_argument(
        '--auto',
        metavar='FOLDER',
        help='Automatically process all headers{x}.txt files in the specified folder and update corresponding user{x}.json files'
    )
    parser.add_argument(
        '--user-id',
        help='User ID to match in user.json (required if not using --auto)'
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

    # Handle --auto mode
    if args.auto:
        process_auto_folder(args.auto)
        return

    # Validate required arguments for manual mode
    if not args.user_id:
        parser.error("--user-id is required when not using --auto mode")

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
        print(f"{key}: {display_value}")

    # Update user.json
    print()
    update_user_json(args.user_id, extracted_data, args.user_json)


if __name__ == '__main__':
    main()
