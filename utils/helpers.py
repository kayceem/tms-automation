"""Utility functions for the TMS automation bot."""

import json
from typing import Dict, Any
from pathlib import Path


def load_json_file(file_path: str) -> Dict[str, Any]:
    """
    Load JSON data from a file.

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON data as dictionary

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, 'r') as f:
        return json.load(f)


def load_client_data(file_path: str) -> Dict[str, Any]:
    """
    Load client data from JSON file.

    Args:
        file_path: Path to client data JSON file

    Returns:
        Client data dictionary
    """
    return load_json_file(file_path)


def load_order_params(file_path: str) -> Dict[str, Any]:
    """
    Load order parameters from JSON file.

    Args:
        file_path: Path to order parameters JSON file

    Returns:
        Order parameters dictionary
    """
    return load_json_file(file_path)


def save_json_file(data: Dict[str, Any], file_path: str, indent: int = 2):
    """
    Save data to JSON file.

    Args:
        data: Data to save
        file_path: Path to save file
        indent: JSON indentation level
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w') as f:
        json.dump(data, f, indent=indent)


def validate_positive_number(value: Any, name: str) -> float:
    """
    Validate that a value is a positive number.

    Args:
        value: Value to validate
        name: Name of the parameter (for error messages)

    Returns:
        Validated float value

    Raises:
        ValueError: If value is not a positive number
    """
    try:
        num = float(value)
        if num <= 0:
            raise ValueError(f"{name} must be a positive number")
        return num
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid {name}: {value}") from e


def validate_positive_integer(value: Any, name: str) -> int:
    """
    Validate that a value is a positive integer.

    Args:
        value: Value to validate
        name: Name of the parameter (for error messages)

    Returns:
        Validated integer value

    Raises:
        ValueError: If value is not a positive integer
    """
    try:
        num = int(value)
        if num <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return num
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid {name}: {value}") from e
