"""Configuration management for TMS automation bot."""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


def load_cookies():
    """Load cookies from cookies.json file if it exists, otherwise return empty dict."""
    cookies_path = Path(__file__).parent.parent / 'cookies.json'
    if cookies_path.exists():
        try:
            with open(cookies_path, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


class Settings:
    """Application settings loaded from environment variables."""

    # TMS API Configuration
    TMS_HOST = os.getenv('TMS_HOST', 'tms01.nepsetms.com.np')
    TMS_BASE_URL = os.getenv('TMS_BASE_URL', 'https://tms01.nepsetms.com.np')
    TMS_ORDER_ENDPOINT = '/tmsapi/orderApi/order/'

    # Load cookies from file or environment
    _cookies = load_cookies()

    # Authentication - prioritize cookies.json over environment variables
    XSRF_TOKEN = _cookies.get('XSRF_TOKEN') or os.getenv('XSRF_TOKEN')
    RID_COOKIE = _cookies.get('RID_COOKIE') or os.getenv('RID_COOKIE')
    HOST_SESSION_ID = _cookies.get('HOST_SESSION_ID') or os.getenv('HOST_SESSION_ID')
    ACCESS_TOKEN = _cookies.get('ACCESS_TOKEN') or os.getenv('ACCESS_TOKEN')

    # Client Information
    REQUEST_OWNER = os.getenv('REQUEST_OWNER', '175309')
    MEMBER_CODE = os.getenv('MEMBER_CODE', '1')

    # Order Defaults
    DEFAULT_ORDER_TYPE = os.getenv('DEFAULT_ORDER_TYPE', 'LMT')
    DEFAULT_ORDER_VALIDITY = os.getenv('DEFAULT_ORDER_VALIDITY', 'DAY')
    DEFAULT_PRODUCT_CODE = os.getenv('DEFAULT_PRODUCT_CODE', 'CNC')
    DEFAULT_INSTRUMENT_TYPE = os.getenv('DEFAULT_INSTRUMENT_TYPE', 'EQ')
    DEFAULT_BUY_OR_SELL = int(os.getenv('DEFAULT_BUY_OR_SELL', '1'))

    @classmethod
    def validate(cls):
        """Validate that required settings are present."""
        required = ['XSRF_TOKEN', 'RID_COOKIE', 'HOST_SESSION_ID', 'ACCESS_TOKEN']
        missing = [key for key in required if not getattr(cls, key)]

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Please ensure your .env file is properly configured."
            )


settings = Settings()
