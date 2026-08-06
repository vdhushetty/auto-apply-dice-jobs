import os
import time
from pathlib import Path
from urllib.parse import urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv, set_key, find_dotenv

from core.authorization import require_dice_automation_authorized


LOGIN_PAGE_URL = "https://www.dice.com/dashboard/login"
ACCOUNT_PROFILE_URL = "https://www.dice.com/profile/info"
AUTHENTICATED_PROFILE_PATHS = {"/dashboard/profiles", "/profile/info"}
COOKIE_TRANSFER_KEYS = {
    "name",
    "value",
    "path",
    "domain",
    "secure",
    "httpOnly",
    "expiry",
    "sameSite",
}


def _profile_page_confirms_authenticated_session(
    current_url,
    body_text,
    login_form_visible,
    account_control_visible,
    page_ready=True,
):
    """Return True only when Dice's protected profile page shows account-only content."""

    current_path = urlparse(current_url or "").path.rstrip("/").lower()
    normalized_body = (body_text or "").lower()
    if current_path not in AUTHENTICATED_PROFILE_PATHS or login_form_visible or not page_ready:
        return False
    if not normalized_body.strip():
        return False
    if any(
        marker in normalized_body
        for marker in (
            "log in to continue",
            "create an account or sign in",
            "checking your session",
            "make your next move",
            "verify you are human",
            "oops! it looks like this page doesn't exist",
        )
    ):
        return False
    profile_markers = (
        "my profile",
        "career profile",
        "profile information",
        "profile visibility",
        "complete your experience",
        "upload resume",
    )
    # A protected-looking URL alone is not authentication evidence: Dice may preserve the URL
    # while rendering a login, challenge, or generic error surface. Require an account control or
    # known account-only profile content, and fail closed if Dice changes both.
    return account_control_visible or any(
        marker in normalized_body for marker in profile_markers
    )


def _validation_failure(message, failure_callback=None):
    print(f"Login failed: {message}")
    if failure_callback is not None:
        failure_callback(message)
    return False


def _transferable_cookie(cookie):
    """Return a Selenium-compatible copy of a browser cookie, or ``None``."""

    if not isinstance(cookie, dict):
        return None
    name = cookie.get("name")
    value = cookie.get("value")
    if not isinstance(name, str) or not name or not isinstance(value, str):
        return None
    domain = cookie.get("domain")
    if not isinstance(domain, str):
        return None
    normalized_domain = domain.lstrip(".").lower()
    if normalized_domain != "dice.com" and not normalized_domain.endswith(".dice.com"):
        return None

    transferable = {key: cookie[key] for key in COOKIE_TRANSFER_KEYS if key in cookie}
    if "expiry" in transferable:
        try:
            transferable["expiry"] = int(transferable["expiry"])
        except (TypeError, ValueError, OverflowError):
            transferable.pop("expiry", None)
    if transferable.get("sameSite") not in {"Strict", "Lax", "None"}:
        transferable.pop("sameSite", None)
    return transferable


def normalize_dice_session_cookies(cookies):
    """Return only transferable Dice-domain cookies from an untrusted cookie sequence."""

    return tuple(
        transferable
        for cookie in cookies
        if (transferable := _transferable_cookie(cookie)) is not None
    )


def get_dice_session_cookies(driver):
    """Capture only transferable Dice-domain cookies for short-lived in-memory reuse."""

    return normalize_dice_session_cookies(driver.get_cookies())


def _driver_confirms_authenticated_profile(driver):
    """Inspect the current protected profile page without logging sensitive content."""

    account_control_visible = any(
        element.is_displayed()
        for selector in (
            '[data-testid="user-menu"]',
            '[data-testid="profile-menu"]',
            'button[aria-label*="account" i]',
            'button[aria-label*="profile" i]',
        )
        for element in driver.find_elements(By.CSS_SELECTOR, selector)
    )
    login_form_visible = any(
        element.is_displayed()
        for selector in ('input[name="email"]', 'input[name="password"]')
        for element in driver.find_elements(By.CSS_SELECTOR, selector)
    )
    body_elements = driver.find_elements(By.TAG_NAME, "body")
    body_text = body_elements[0].text if body_elements else ""
    page_ready = driver.execute_script("return document.readyState") == "complete"
    return _profile_page_confirms_authenticated_session(
        driver.current_url,
        body_text,
        login_form_visible,
        account_control_visible,
        page_ready,
    )


def _wait_for_authenticated_profile(driver, timeout):
    """Navigate to Dice's protected profile route and wait for authenticated content."""

    driver.get(ACCOUNT_PROFILE_URL)
    deadline = time.monotonic() + max(0, timeout)
    while True:
        if _driver_confirms_authenticated_profile(driver):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def restore_dice_session(driver, cookies, timeout=15):
    """Restore an in-memory Dice session and verify it on a protected route.

    Cookie restoration is best effort.  Callers must fall back to the normal credential
    login when this returns ``False``.
    """

    require_dice_automation_authorized()
    if not cookies:
        return False

    try:
        driver.get("https://www.dice.com/")
        try:
            driver.delete_all_cookies()
        except Exception:
            pass

        added = 0
        for transferable in normalize_dice_session_cookies(cookies):
            try:
                driver.add_cookie(transferable)
                added += 1
            except Exception:
                # A nonessential analytics or cross-domain cookie must not prevent the
                # authenticated Dice cookies from being tried.
                continue
        if not added:
            return False

        return _wait_for_authenticated_profile(driver, timeout)
    except Exception:
        return False


def update_dice_credentials(username, password, update_env=True):
    """
    Updates the Dice credentials in the .env file.

    Parameters:
        username (str): Dice account email/username
        password (str): Dice account password
        update_env (bool): Whether to update the .env file or not

    Returns:
        bool: True if credentials were updated successfully
    """
    if not username or not password:
        print("Invalid credentials provided. Both username and password are required.")
        return False

    try:
        if update_env:
            # Find or create .env file
            dotenv_path = find_dotenv()
            if not dotenv_path:
                dotenv_path = os.path.join(os.getcwd(), ".env")
                Path(dotenv_path).touch(exist_ok=True)
                print("Created a local .env file.")

            # Load existing .env file
            load_dotenv(dotenv_path)

            # Update credentials in .env file
            set_key(dotenv_path, "DICE_USERNAME", username)
            set_key(dotenv_path, "DICE_PASSWORD", password)
            if os.name != "nt":
                os.chmod(dotenv_path, 0o600)
            print("Dice credentials updated in .env file.")

        # Set the environment variables for current session
        os.environ["DICE_USERNAME"] = username
        os.environ["DICE_PASSWORD"] = password

        return True
    except Exception as e:
        print(f"Error updating credentials: {e}")
        return False


def get_headless_driver():
    """
    Creates a headless WebDriver for credential validation with browser fallback.

    Returns:
        webdriver: A headless Chrome/Brave WebDriver instance
    """
    return get_validation_driver(headless=True)


def get_validation_driver(headless=True):
    """Create the shared validation driver in visible or headless mode."""

    from core.main_script import get_web_driver

    driver = get_web_driver(headless=headless)
    driver.set_page_load_timeout(25)
    return driver


def validate_dice_credentials(
    username,
    password,
    headless=True,
    failure_callback=None,
    session_callback=None,
):
    """
    Validates Dice credentials by attempting to log in using a headless browser.
    With enhanced waiting times for slow login processes.

    Parameters:
        username (str): Dice account email/username
        password (str): Dice account password
        headless (bool): Whether to use headless mode for validation

    Returns:
        bool: True if login was successful, False otherwise
    """
    require_dice_automation_authorized()
    print("Validating Dice credentials...")

    driver = get_validation_driver(headless=headless)

    try:
        overall_deadline = time.monotonic() + 80

        def wait_for(condition):
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Dice login validation exceeded 80 seconds.")
            return WebDriverWait(driver, min(20, remaining)).until(condition)

        # Try login with provided credentials
        driver.get(LOGIN_PAGE_URL)

        # Enter email/username
        email_field = wait_for(EC.presence_of_element_located((By.NAME, "email")))
        email_field.clear()
        email_field.send_keys(username)

        # Click continue
        continue_button = wait_for(
            EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='sign-in-button']"))
        )
        continue_button.click()

        # Enter password
        password_field = wait_for(EC.presence_of_element_located((By.NAME, "password")))
        password_field.clear()
        password_field.send_keys(password)

        # Click login button
        login_button = wait_for(
            EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='submit-password']"))
        )
        login_button.click()

        # Wait for Dice to finish the sign-in response, but do not treat a public job-search
        # page as proof of authentication.
        error_selectors = (
            '[role="alert"]',
            '[data-testid*="error"]',
            ".error-message",
            ".alert-danger",
        )
        transition_deadline = min(overall_deadline - 20, time.monotonic() + 30)
        while time.monotonic() < transition_deadline:
            current_url = (driver.current_url or "").lower()
            if not any(marker in current_url for marker in ("/login", "/signin", "/sign-in")):
                break
            visible_errors = [
                (element.text or "").strip().lower()
                for selector in error_selectors
                for element in driver.find_elements(By.CSS_SELECTOR, selector)
                if element.is_displayed()
            ]
            if any(
                any(
                    word in message
                    for word in (
                        "invalid",
                        "incorrect",
                        "failed",
                        "locked",
                        "not recognized",
                    )
                )
                for message in visible_errors
            ):
                return _validation_failure(
                    "Dice rejected the username or password.",
                    failure_callback,
                )

            body_elements = driver.find_elements(By.TAG_NAME, "body")
            body_text = body_elements[0].text.lower() if body_elements else ""
            verification_markers = (
                "verify you are human",
                "verification code",
                "one-time code",
                "verify your identity",
                "captcha",
            )
            if headless and any(marker in body_text for marker in verification_markers):
                return _validation_failure(
                    "Dice requires interactive verification. Turn off headless mode and retry.",
                    failure_callback,
                )
            time.sleep(0.5)

        # Verify against Dice's protected profile page. Public search forms and URL changes
        # alone are not sufficient evidence that Dice accepted the account session.
        remaining = overall_deadline - time.monotonic()
        if remaining <= 0:
            return _validation_failure(
                "Dice login validation exceeded 80 seconds.",
                failure_callback,
            )
        driver.set_page_load_timeout(max(1, min(25, remaining)))
        driver.get(ACCOUNT_PROFILE_URL)
        while time.monotonic() < overall_deadline:
            account_control_visible = any(
                element.is_displayed()
                for selector in (
                    '[data-testid="user-menu"]',
                    '[data-testid="profile-menu"]',
                    'button[aria-label*="account" i]',
                    'button[aria-label*="profile" i]',
                )
                for element in driver.find_elements(By.CSS_SELECTOR, selector)
            )
            login_form_visible = any(
                element.is_displayed()
                for selector in ('input[name="email"]', 'input[name="password"]')
                for element in driver.find_elements(By.CSS_SELECTOR, selector)
            )
            body_elements = driver.find_elements(By.TAG_NAME, "body")
            body_text = body_elements[0].text if body_elements else ""
            page_ready = driver.execute_script("return document.readyState") == "complete"
            if _profile_page_confirms_authenticated_session(
                driver.current_url,
                body_text,
                login_form_visible,
                account_control_visible,
                page_ready,
            ):
                print("Login successful with provided credentials!")
                if session_callback is not None:
                    try:
                        session_callback(get_dice_session_cookies(driver))
                    except Exception:
                        # Session reuse is optional; cookie capture must never turn a valid
                        # credential check into a failure.
                        pass
                return True
            if login_form_visible and "/login" in (driver.current_url or "").lower():
                return _validation_failure(
                    "Dice returned to the sign-in page. Check the username and password.",
                    failure_callback,
                )
            time.sleep(0.5)
        final_path = urlparse(driver.current_url or "").path or "/"
        return _validation_failure(
            "Dice did not confirm an authenticated session within 80 seconds "
            f"(final page: {final_path}). Turn off headless mode if Dice requires verification.",
            failure_callback,
        )

    except Exception as e:
        print(f"Error validating credentials: {e}")
        if failure_callback is not None:
            failure_callback(str(e))
        return False
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def login_to_dice(driver, credentials_from_params=None):
    """
    Logs into Dice using credentials from the .env file or provided parameters.
    With enhanced waiting and retry logic for slow login processes.

    Parameters:
        driver (selenium.webdriver): Selenium WebDriver instance.
        credentials_from_params (tuple): Optional (username, password) tuple to use instead of .env

    Returns:
        bool: True if login is successful, False otherwise.
    """
    require_dice_automation_authorized()
    # Load credentials from parameters or environment
    if credentials_from_params and len(credentials_from_params) == 2:
        username, password = credentials_from_params
    else:
        # Load from environment
        load_dotenv()
        username = os.getenv("DICE_USERNAME")
        password = os.getenv("DICE_PASSWORD")

    if not username or not password:
        raise Exception(
            "Dice credentials not found. Please set DICE_USERNAME and DICE_PASSWORD in .env file or provide them as parameters."
        )

    # Navigate to login page
    print("Navigating to Dice login page...")
    driver.get("https://www.dice.com/dashboard/login")

    # Set up the wait used for the two credential form steps.
    short_wait = WebDriverWait(driver, 20)

    try:
        # Enter email/username
        print("Entering username...")
        email_field = short_wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_field.clear()
        email_field.send_keys(username)

        # Click continue button
        print("Clicking continue button...")
        continue_button = short_wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='sign-in-button']"))
        )
        continue_button.click()
        time.sleep(3)  # Increased pause to ensure page transitions

        # Enter password
        print("Entering password...")
        password_field = short_wait.until(EC.presence_of_element_located((By.NAME, "password")))
        password_field.clear()
        password_field.send_keys(password)

        # Click login button
        print("Clicking login button...")
        login_button = short_wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='submit-password']"))
        )
        login_button.click()

        # Add a longer pause after clicking login
        print("Waiting for login to complete (this may take some time)...")
        time.sleep(10)  # Increased wait time after login click

        # A public search form or /jobs URL is not proof of authentication. Confirm the
        # browser session against Dice's protected profile page, exactly as Test Login does.
        print("Verifying login on Dice's protected profile page...")
        if _wait_for_authenticated_profile(driver, timeout=45):
            print("Login verified on protected profile page!")
            return True
        print("Dice did not confirm an authenticated profile session.")
        return False

    except Exception as e:
        print(f"Login process failed: {e}")
        return False


def authenticate_dice_session(
    driver,
    credentials,
    session_cookies=None,
    status_callback=None,
):
    """Reuse a verified in-memory session, then safely fall back to credential login.

    Returns ``(authenticated, reused_session)``. No credential or cookie values are logged or
    passed to the status callback.
    """

    if session_cookies:
        if status_callback is not None:
            status_callback("Restoring verified Dice session...")
        if restore_dice_session(driver, session_cookies):
            if status_callback is not None:
                status_callback("Verified Dice session restored. Fetching jobs...")
            return True, True
        if status_callback is not None:
            status_callback("Verified Dice session expired; signing in again...")
    elif status_callback is not None:
        status_callback("Signing in to Dice...")

    authenticated = login_to_dice(driver, credentials)
    if authenticated and status_callback is not None:
        status_callback("Login successful. Fetching jobs...")
    return authenticated, False


def setup_credentials_interactive(headless=True):
    """
    Interactive command-line setup for Dice credentials.
    Tests login before saving to .env file.

    Parameters:
        headless (bool): Whether to use headless mode for validation

    Returns:
        bool: True if credentials were successfully set up
    """
    print("\n=== Dice Credentials Setup ===")
    print("Please enter your Dice.com login information.")

    username = input("Email/Username: ").strip()
    password = input("Password: ").strip()

    if not username or not password:
        print("Both username and password are required.")
        return False

    # Validate the credentials
    if validate_dice_credentials(username, password, headless=headless):
        # Save to .env file
        update_dice_credentials(username, password)
        return True
    else:
        print("Invalid credentials. Please try again.")
        return False


if __name__ == "__main__":
    # This allows running the file directly for credential setup
    try:
        print("Starting Dice credential setup...")
        success = False

        while not success:
            success = setup_credentials_interactive(headless=True)
            if not success:
                retry = input("Would you like to try again? (y/n): ").lower()
                if retry != "y":
                    break

        if success:
            print("Credential setup complete! You can now run the main application.")
        else:
            print(
                "Credential setup was not completed. You will need to set up credentials before using the application."
            )

    except Exception as e:
        print(f"An error occurred during setup: {e}")
