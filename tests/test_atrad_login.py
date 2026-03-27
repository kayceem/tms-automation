"""Tests for ATRAD login functionality.

For real integration tests that hit the actual ATRAD server,
see tests/test_atrad_login_real.py
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from config.atrad_user_config import ATRADUserConfig
from api.atrad_client import ATRADClient


class TestATRADLogin:
    """Test suite for ATRAD login functionality."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        # Create test user config
        self.user_config = ATRADUserConfig(
            user_id="test_atrad_user",
            atrad_base_url="https://tms.stockhouse.com.np",
            atrad_host="tms.stockhouse.com.np",
            username="TEST_USER",
            password="TEST_PASSWORD",
            account_id="12345"
        )

    @patch('api.atrad_client.requests.Session')
    def test_login_success(self, mock_session_class):
        """Test successful login with valid credentials."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock successful login response
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "description": "success",
            "role": "OnlineUser",
            "broker_code": "NSH",
            "watchID": "101305"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response

        # Mock cookies
        mock_session.cookies.get.return_value = "TEST_SESSION_ID"

        # Create client and login
        client = ATRADClient(self.user_config)
        result = client.login()

        # Verify POST request was made with correct data
        assert mock_session.post.called
        call_args = mock_session.post.call_args

        # Verify endpoint
        assert call_args[0][0] == "https://tms.stockhouse.com.np/atsweb/login"

        # Verify payload is sent as form data (dictionary, not JSON string)
        payload = call_args[1]['data']
        assert isinstance(payload, dict), "Payload should be a dict for form-encoding"
        assert payload['action'] == 'login'
        assert payload['format'] == 'json'
        assert payload['txtUserName'] == 'TEST_USER'
        assert payload['txtPassword'] == 'TEST_PASSWORD'

        # Headers are now set globally in session.headers, not per-request
        # Verify global session headers
        assert mock_session.headers.update.called
        header_update_call = mock_session.headers.update.call_args[0][0]
        assert header_update_call['X-Requested-With'] == 'XMLHttpRequest'
        assert header_update_call['Content-Type'] == 'application/x-www-form-urlencoded'

        # Verify 'data' parameter used (not 'json')
        assert 'data' in call_args[1]
        assert 'json' not in call_args[1]

        # Verify response
        assert result['code'] == '0'
        assert result['description'] == 'success'
        assert result['role'] == 'OnlineUser'
        assert result['broker_code'] == 'NSH'

        # Verify authentication state
        assert client.is_authenticated()

        # Verify user_config session was updated
        assert self.user_config._session_id == 'TEST_SESSION_ID'
        assert self.user_config._role == 'OnlineUser'
        assert self.user_config._broker_code == 'NSH'

    @patch('api.atrad_client.requests.Session')
    def test_login_failure_invalid_credentials(self, mock_session_class):
        """Test login failure with invalid credentials."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock failed login response
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "1",
            "description": "Invalid username or password"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response

        # Create client and attempt login
        client = ATRADClient(self.user_config)

        # Login should raise exception for failed login
        with pytest.raises(Exception) as exc_info:
            client.login()

        assert "Login failed" in str(exc_info.value)
        assert "Invalid username or password" in str(exc_info.value)

        # Verify authentication state is false
        assert not client.is_authenticated()

        # Verify user_config session was NOT updated
        assert self.user_config._session_id is None
        assert self.user_config._role is None
        assert self.user_config._broker_code is None

    @patch('api.atrad_client.requests.Session')
    def test_login_failure_account_locked(self, mock_session_class):
        """Test login failure when account is locked."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock locked account response
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "2",
            "description": "Account is locked"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response

        # Create client and attempt login
        client = ATRADClient(self.user_config)

        # Login should raise exception for locked account
        with pytest.raises(Exception) as exc_info:
            client.login()

        assert "Login failed" in str(exc_info.value)
        assert "Account is locked" in str(exc_info.value)

        # Verify authentication state is false
        assert not client.is_authenticated()

    @patch('api.atrad_client.requests.Session')
    def test_login_network_error(self, mock_session_class):
        """Test login failure due to network error."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock network error
        import requests
        mock_session.post.side_effect = requests.exceptions.ConnectionError("Connection failed")

        # Create client and attempt login
        client = ATRADClient(self.user_config)

        # Login should raise RequestException
        with pytest.raises(requests.exceptions.RequestException):
            client.login()

        # Verify authentication state is false
        assert not client.is_authenticated()

    @patch('api.atrad_client.requests.Session')
    def test_login_session_id_capture(self, mock_session_class):
        """Test that session ID (JSESSIONID) is properly captured."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock successful login response
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "description": "success",
            "role": "OnlineUser",
            "broker_code": "NSH"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response

        # Mock specific JSESSIONID
        test_session_id = "ABCD1234EFGH5678"
        mock_session.cookies.get.return_value = test_session_id

        # Create client and login
        client = ATRADClient(self.user_config)
        result = client.login()

        # Verify session ID was captured
        mock_session.cookies.get.assert_called_with('JSESSIONID')
        assert self.user_config._session_id == test_session_id

    @patch('api.atrad_client.requests.Session')
    def test_login_different_broker_codes(self, mock_session_class):
        """Test login with different broker codes."""
        broker_codes = ['NSH', 'ABC', 'XYZ', 'DEF']

        for broker_code in broker_codes:
            # Reset user config
            self.user_config = ATRADUserConfig(
                user_id="test_user",
                atrad_base_url="https://tms.stockhouse.com.np",
                atrad_host="tms.stockhouse.com.np",
                username="TEST_USER",
                password="TEST_PASSWORD",
                account_id="12345"
            )

            # Create mock session instance
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            # Mock response with specific broker code
            mock_response = Mock()
            mock_response.json.return_value = {
                "code": "0",
                "description": "success",
                "role": "OnlineUser",
                "broker_code": broker_code
            }
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response
            mock_session.cookies.get.return_value = "TEST_SESSION"

            # Create client and login
            client = ATRADClient(self.user_config)
            result = client.login()

            # Verify broker code
            assert result['broker_code'] == broker_code
            assert self.user_config._broker_code == broker_code

    @patch('api.atrad_client.requests.Session')
    def test_login_different_roles(self, mock_session_class):
        """Test login with different user roles."""
        roles = ['OnlineUser', 'Admin', 'BranchUser', 'SuperAdmin']

        for role in roles:
            # Reset user config
            self.user_config = ATRADUserConfig(
                user_id="test_user",
                atrad_base_url="https://tms.stockhouse.com.np",
                atrad_host="tms.stockhouse.com.np",
                username="TEST_USER",
                password="TEST_PASSWORD",
                account_id="12345"
            )

            # Create mock session instance
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            # Mock response with specific role
            mock_response = Mock()
            mock_response.json.return_value = {
                "code": "0",
                "description": "success",
                "role": role,
                "broker_code": "NSH"
            }
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response
            mock_session.cookies.get.return_value = "TEST_SESSION"

            # Create client and login
            client = ATRADClient(self.user_config)
            result = client.login()

            # Verify role
            assert result['role'] == role
            assert self.user_config._role == role

    @patch('api.atrad_client.requests.Session')
    def test_multiple_login_calls(self, mock_session_class):
        """Test multiple consecutive login calls."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock successful login response
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "description": "success",
            "role": "OnlineUser",
            "broker_code": "NSH"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response
        mock_session.cookies.get.return_value = "TEST_SESSION"

        # Create client
        client = ATRADClient(self.user_config)

        # Execute login multiple times
        for _ in range(3):
            result = client.login()
            assert result['code'] == '0'
            assert client.is_authenticated()

        # Verify login was called 3 times
        assert mock_session.post.call_count == 3

    @patch('api.atrad_client.requests.Session')
    def test_ensure_authenticated_when_not_logged_in(self, mock_session_class):
        """Test ensure_authenticated triggers login when not authenticated."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock successful login response
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "description": "success",
            "role": "OnlineUser",
            "broker_code": "NSH"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response
        mock_session.cookies.get.return_value = "TEST_SESSION"

        # Create client
        client = ATRADClient(self.user_config)

        # Verify not authenticated initially
        assert not client.is_authenticated()

        # Call ensure_authenticated
        client.ensure_authenticated()

        # Verify now authenticated
        assert client.is_authenticated()

        # Verify login was called
        assert mock_session.post.call_count == 1

    @patch('api.atrad_client.requests.Session')
    def test_ensure_authenticated_when_already_logged_in(self, mock_session_class):
        """Test ensure_authenticated does not re-login when already authenticated."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock successful login response
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "description": "success",
            "role": "OnlineUser",
            "broker_code": "NSH"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response
        mock_session.cookies.get.return_value = "TEST_SESSION"

        # Create client and login
        client = ATRADClient(self.user_config)
        client.login()

        # Reset call count
        mock_session.post.reset_mock()

        # Call ensure_authenticated
        client.ensure_authenticated()

        # Verify login was NOT called again
        assert mock_session.post.call_count == 0

    @patch('api.atrad_client.requests.Session')
    def test_login_response_with_additional_fields(self, mock_session_class):
        """Test login response that includes additional optional fields."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock response with extra fields
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "description": "success",
            "role": "OnlineUser",
            "broker_code": "NSH",
            "watchID": "101305",
            "userName": "TEST_USER",
            "accountStatus": "active",
            "lastLoginTime": "2025-03-27 10:00:00"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response
        mock_session.cookies.get.return_value = "TEST_SESSION"

        # Create client and login
        client = ATRADClient(self.user_config)
        result = client.login()

        # Verify all fields are present
        assert result['code'] == '0'
        assert result['role'] == 'OnlineUser'
        assert result['broker_code'] == 'NSH'
        assert result['watchID'] == '101305'
        assert result['userName'] == 'TEST_USER'
        assert result['accountStatus'] == 'active'
        assert result['lastLoginTime'] == '2025-03-27 10:00:00'

    @patch('api.atrad_client.requests.Session')
    def test_login_thread_safety(self, mock_session_class):
        """Test that login uses thread-safe locking mechanism."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock successful login response
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "description": "success",
            "role": "OnlineUser",
            "broker_code": "NSH"
        }
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response
        mock_session.cookies.get.return_value = "TEST_SESSION"

        # Create client
        client = ATRADClient(self.user_config)

        # Verify login lock exists
        assert hasattr(client, '_login_lock')
        assert hasattr(client, '_request_lock')

        # Login should succeed
        result = client.login()
        assert result['code'] == '0'

    @patch('api.atrad_client.requests.Session')
    def test_login_http_error_handling(self, mock_session_class):
        """Test login handles HTTP errors properly."""
        # Create mock session instance
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock HTTP error (500 Internal Server Error)
        import requests
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_session.post.return_value = mock_response

        # Create client and attempt login
        client = ATRADClient(self.user_config)

        # Login should raise HTTPError
        with pytest.raises(requests.exceptions.HTTPError):
            client.login()

        # Verify authentication state is false
        assert not client.is_authenticated()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
