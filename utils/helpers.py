"""Utility functions for the TMS automation bot."""

import json
from typing import Dict, Any, Tuple, Union
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


def detect_system_from_config(config_data: Dict[str, Any]) -> str:
    """
    Detect which trading system (TMS or ATRAD) based on configuration data.

    Args:
        config_data: User configuration dictionary

    Returns:
        'tms' or 'atrad'
    """
    # Check for explicit 'system' field
    if 'system' in config_data:
        system = config_data['system'].lower()
        if system in ['tms', 'atrad']:
            return system

    # Fallback: detect based on presence of fields
    # ATRAD has: username, password, atrad_base_url
    # TMS has: xsrf_token, rid_cookie, access_token, tms_host
    if 'username' in config_data and 'password' in config_data:
        return 'atrad'
    elif 'xsrf_token' in config_data and 'rid_cookie' in config_data:
        return 'tms'

    # Default to TMS for backward compatibility
    return 'tms'


def initialize_order_client_and_service(config_path: str) -> Tuple[Union['TMSClient', 'ATRADClient'], Union['OrderService', 'ATRADOrderService'], str]:
    """
    Initialize the appropriate client and order service based on system type.

    Args:
        config_path: Path to user configuration JSON file

    Returns:
        Tuple of (client, order_service, system_type)

    Raises:
        ValueError: If system type is invalid or configuration is incomplete
    """
    from config.models import ATRADUserConfig, UserConfig
    from api import TMSClient, ATRADClient
    from services.orders import OrderService, ATRADOrderService

    # Load config to detect system
    config_data = load_json_file(config_path)
    system = detect_system_from_config(config_data)

    if system == 'atrad':
        # Initialize ATRAD system
        user_config = ATRADUserConfig.from_file(config_path)
        client = ATRADClient(user_config)
        order_service = ATRADOrderService(client)
        return client, order_service, 'atrad'
    else:
        # Initialize TMS system (default)
        user_config = UserConfig.from_file(config_path)
        client = TMSClient(user_config)
        order_service = OrderService(client)
        return client, order_service, 'tms'
