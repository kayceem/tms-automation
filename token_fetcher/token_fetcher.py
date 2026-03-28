import json
import time
from pathlib import Path
from typing import Dict, Optional
from playwright.sync_api import sync_playwright, Page, Browser
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import io
import cv2
import numpy as np


class TokenFetcher:
    """
    A class to automate login and fetch authentication tokens using Playwright.
    Uses Tesseract OCR to solve captcha challenges.
    """

    # Valid captcha characters (0-9, A-Z, a-z)
    VALID_CHARS = set(list(range(48, 58)) + list(range(65, 91)) + list(range(97, 123)))

    def __init__(self, headless: bool = True, manual_captcha: bool = False, debug_images: bool = False):
        """
        Initialize the TokenFetcher.

        Args:
            headless: Whether to run browser in headless mode
            manual_captcha: If True, prompt user to manually enter captcha instead of OCR
            debug_images: If True, save captcha images for debugging
        """
        self.headless = headless
        self.manual_captcha = manual_captcha
        self.debug_images = debug_images
        self.base_dir = Path(__file__).parent
        self.users_dir = self.base_dir / "users"
        self.output_dir = Path(__file__).parent.parent / "users"

    def clean_captcha_text(self, text: str) -> str:
        """
        Clean captcha text by removing invalid characters.
        Based on the original TMS code's character filtering.

        Args:
            text: Raw OCR output text

        Returns:
            Cleaned text containing only valid characters
        """
        cleaned = ""
        for char in text:
            if ord(char) in self.VALID_CHARS:
                cleaned += char
        return cleaned

    def load_credentials(self, user_number: int) -> Dict:
        """
        Load user credentials from JSON file.

        Args:
            user_number: User number (1, 2, 3, etc.)

        Returns:
            Dictionary containing user_id, username, password, and login_url
        """
        cred_file = self.users_dir / f"user_cred{user_number}.json"

        if not cred_file.exists():
            raise FileNotFoundError(f"Credentials file not found: {cred_file}")

        with open(cred_file, 'r') as f:
            return json.load(f)

    def fetch_token(self, user_number: int, max_retries: int = 3) -> Dict:
        """
        Fetch authentication token for a user.

        Args:
            user_number: User number (1, 2, 3, etc.)
            max_retries: Maximum number of login attempts

        Returns:
            Dictionary containing tokens and cookies
        """
        credentials = self.load_credentials(user_number)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context()
            page = context.new_page()

            try:
                # Navigate to login page
                page.goto(credentials['login_url'])
                page.wait_for_load_state('networkidle')
                time.sleep(1)

                for attempt in range(max_retries):
                    print(f"Login attempt {attempt + 1}/{max_retries} for user {user_number}")

                    # Fill username
                    username_xpath = "/html/body/app-root/app-login/div/div/div[2]/form/div[1]/input"
                    page.locator(f"xpath={username_xpath}").fill(credentials['username'])
                    time.sleep(0.5)

                    # Fill password
                    password_xpath = "//*[@id='password-field']"
                    page.locator(f"xpath={password_xpath}").fill(credentials['password'])
                    time.sleep(0.5)

                    captcha_image_xpath = "/html/body/app-root/app-login/div/div/div[2]/form/div[3]/div[2]/div/img"
                    # Solve captcha
                    captcha_text = input("Enter captcha manually: ")

                    if not captcha_text:
                        print(f"Failed to solve captcha on attempt {attempt + 1}")
                        page.reload()
                        page.wait_for_load_state('networkidle')
                        time.sleep(1)
                        continue

                    print(f"Captcha solved: {captcha_text}")

                    # Fill captcha
                    captcha_input_xpath = "//*[@id='captchaEnter']"
                    page.locator(f"xpath={captcha_input_xpath}").fill(captcha_text)
                    time.sleep(1)

                    # Click login button
                    login_button_xpath = "/html/body/app-root/app-login/div/div/div[2]/form/div[4]/input"

                    # Setup response listener to capture tokens
                    tokens = {}

                    def handle_response(response):
                        nonlocal tokens
                        # Capture cookies from response headers
                        set_cookie_header = response.headers.get('set-cookie', '')
                        if set_cookie_header:
                            tokens['set_cookie_raw'] = set_cookie_header

                    page.on('response', handle_response)

                    # Click login
                    page.locator(f"xpath={login_button_xpath}").click()

                    # Wait for navigation or error
                    try:
                        time.sleep(0.5)
                        page.wait_for_load_state('networkidle', timeout=10000)
                    except Exception:
                        pass

                    # Get cookies from browser context
                    cookies = context.cookies()

                    # Extract specific cookies
                    cookie_dict = {}
                    for cookie in cookies:
                        if cookie['name'] in ['_rid', '_aid', 'XSRF-TOKEN', 'XSRF-TOKKEN']:
                            cookie_dict[cookie['name']] = cookie['value']

                    # Check if login was successful by verifying we have cookies
                    if cookie_dict:
                        print(f"Login successful for user {user_number}")

                        # Save tokens to user file
                        self.save_tokens(user_number, credentials, cookie_dict, cookies)

                        browser.close()
                        return {
                            'success': True,
                            'cookies': cookie_dict,
                            'all_cookies': cookies
                        }
                    else:
                        print(f"Login failed on attempt {attempt + 1}")
                        # Refresh page for next attempt
                        page.reload()
                        page.wait_for_load_state('networkidle')

                browser.close()
                return {
                    'success': False,
                    'error': 'Max retries reached'
                }

            except Exception as e:
                browser.close()
                return {
                    'success': False,
                    'error': str(e)
                }

    def save_tokens(self, user_number: int, credentials: Dict, cookies: Dict, all_cookies: list):
        """
        Save tokens to user JSON file.

        Args:
            user_number: User number
            credentials: User credentials dictionary
            cookies: Dictionary of specific cookies
            all_cookies: List of all cookies
        """
        output_file = self.output_dir / f"user{user_number}.json"

        # Load existing user data if it exists
        user_data = {}
        if output_file.exists():
            with open(output_file, 'r') as f:
                user_data = json.load(f)

        if 'user_id' not in user_data:
            print(f"No existing user json.")
            return
        
        if user_data['user_id'] != credentials['user_id']:
            print(f"User ID mismatch. Expected {credentials['user_id']}, found {user_data['user_id']}. Skipping token update.")
            return
     
        # Update with new tokens
        if '_rid' in cookies:
            user_data['rid_cookie'] = cookies['_rid']
        if '_aid' in cookies:
            user_data['access_token'] = cookies['_aid']
        if 'XSRF-TOKEN' in cookies or 'XSRF-TOKKEN' in cookies:
            user_data['xsrf_token'] = cookies.get('XSRF-TOKEN', cookies.get('XSRF-TOKKEN'))

        # Save to file
        with open(output_file, 'w') as f:
            json.dump(user_data, f, indent=2)

        print(f"Tokens saved to {output_file}")

    def fetch_all_users(self, user_count: int):
        """
        Fetch tokens for multiple users.

        Args:
            user_count: Number of users to process
        """
        results = {}

        for user_num in range(1, user_count + 1):
            print(f"\n{'='*50}")
            print(f"Processing user {user_num}")
            print(f"{'='*50}")

            result = self.fetch_token(user_num)
            results[f"user{user_num}"] = result

            if result['success']:
                print(f"✓ User {user_num}: Success")
            else:
                print(f"✗ User {user_num}: Failed - {result.get('error', 'Unknown error')}")

            # Small delay between users
            time.sleep(2)

        return results


if __name__ == "__main__":
    # Example usage
    fetcher = TokenFetcher(headless=True)  # Set to True for headless mode

    # Fetch token for a single user
    result = fetcher.fetch_token(1)
    print(f"\nResult: {result}")
