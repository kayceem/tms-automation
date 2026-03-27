"""Real integration tests for ATRAD login (requires valid credentials).

These tests make actual HTTP requests to the ATRAD server.
Run manually with specific test file to avoid running with regular test suite.

Usage:
    # Run single test
    uv run pytest tests/manual/test_atrad_login_real.py::TestATRADLoginReal::test_real_login_with_example_user -v -s

    # Run all real tests
    uv run pytest tests/manual/test_atrad_login_real.py -v -s
"""

from time import time
import pytest
import json
from pathlib import Path
from config.atrad_user_config import ATRADUserConfig
from api.atrad_client import ATRADClient


class TestATRADLoginReal:
    """Real integration tests for ATRAD login (hits actual server)."""

    def test_real_login_with_example_user(self):
        """
        Test real login with actual ATRAD server using example user credentials.

        This test makes actual HTTP requests to the ATRAD server and logs all responses.
        """
        print("\n" + "="*80)
        print("REAL ATRAD LOGIN TEST - Using actual server")
        print("="*80)

        # Load example user config
        example_config_path = Path(__file__).parent.parent.parent / 'users' / 'atrad_user.example.json'
        print(f"\nLoading config from: {example_config_path}")

        with open(example_config_path, 'r') as f:
            config_data = json.load(f)

        print(f"User ID: {config_data['user_id']}")
        print(f"Username: {config_data['username']}")
        print(f"Base URL: {config_data['atrad_base_url']}")
        print(f"Account ID: {config_data['account_id']}")

        # Create user config
        user_config = ATRADUserConfig.from_file(str(example_config_path))

        # Create ATRAD client
        print("\n" + "-"*80)
        print("Creating ATRAD client...")
        print("-"*80)
        client = ATRADClient(user_config)

        print(f"Login endpoint: {client.login_endpoint}")
        print(f"Order endpoint: {client.order_endpoint}")

        # Attempt login
        print("\n" + "-"*80)
        print("Attempting login to ATRAD server...")
        print("-"*80)

        try:
            result = client.login()

            print("\nLOGIN SUCCESSFUL!")
            print("\n" + "-"*80)
            print("Server Response:")
            print("-"*80)


            if result:
                print("\nLogin code indicates SUCCESS (code=0)")

                # Verify authentication state
                assert client.is_authenticated()
                print("Client authentication state: True")

                # Verify session info stored
                print("\n" + "-"*80)
                print("Session Information:")
                print("-"*80)
                print(f"Session ID: {user_config._session_id}")
                print(f"Role: {user_config._role}")
                print(f"Broker Code: {user_config._broker_code}")

                assert user_config._session_id is not None
                print("Session ID captured")

                # Verify session cookies
                print("\n" + "-"*80)
                print("Session Cookies:")
                print("-"*80)
                cookies_dict = dict(client.session.cookies)
                for cookie_name, cookie_value in cookies_dict.items():
                    print(f"{cookie_name}: {cookie_value}")

                assert 'JSESSIONID' in cookies_dict or len(cookies_dict) > 0
                print("Session cookies present")

                print("\n" + "="*80)
                print("REAL LOGIN TEST PASSED ")
                print("="*80)

            else:
                print(f"\n Login failed with code: {result.get('code')}")
                print(f"Description: {result.get('description')}")
                pytest.fail(f"Login failed: {result.get('description')}")

        except Exception as e:
            print(f"\n LOGIN FAILED WITH EXCEPTION!")
            print(f"\nException Type: {type(e).__name__}")
            print(f"Exception Message: {str(e)}")

            # Log full exception details
            import traceback
            print("\n" + "-"*80)
            print("Full Traceback:")
            print("-"*80)
            print(traceback.format_exc())

            # Re-raise to fail the test
            raise

    def test_real_login_and_reauth(self):
        """
        Test real login followed by session validation and re-authentication.

        This test verifies that the session persists and can be reused.
        """
        print("\n" + "="*80)
        print("REAL ATRAD LOGIN + RE-AUTH TEST")
        print("="*80)

        # Load example user config
        example_config_path = Path(__file__).parent.parent.parent / 'users' / 'atrad_user.example.json'
        user_config = ATRADUserConfig.from_file(str(example_config_path))
        client = ATRADClient(user_config)

        # First login
        print("\n[1] First login attempt...")
        result1 = client.login()
        print(f"First login successful: {result1.get('description')}")
        session_id_1 = user_config._session_id

        # Verify authenticated
        assert client.is_authenticated()
        print(f"Session ID: {session_id_1}")

        # Call ensure_authenticated (should not re-login)
        print("\n[2] Calling ensure_authenticated (should NOT re-login)...")
        client.ensure_authenticated()
        print("ensure_authenticated completed")

        # Session should be the same
        assert user_config._session_id == session_id_1
        print(f"Session ID unchanged: {session_id_1}")

        # Force re-login by setting auth to False
        print("\n[3] Forcing re-authentication...")
        client._is_authenticated = False
        client.ensure_authenticated()
        print("Re-authentication completed")

        # Should be authenticated again
        assert client.is_authenticated()
        print(f"Session ID after re-auth: {user_config._session_id}")

        print("\n" + "="*80)
        print("RE-AUTH TEST PASSED ")
        print("="*80)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
