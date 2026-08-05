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
    # Anonymous sessions are redirected away from this protected route. Account controls and
    # known profile copy are useful positive signals, but a fully loaded protected route with no
    # login/challenge/error surface is itself sufficient and avoids brittle text matching.
    return True


def _validation_failure(message, failure_callback=None):
    print(f"Login failed: {message}")
    if failure_callback is not None:
        failure_callback(message)
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
                dotenv_path = os.path.join(os.getcwd(), '.env')
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
            EC.element_to_be_clickable(
                (By.XPATH, "//button[@data-testid='sign-in-button']")
            )
        )
        continue_button.click()
        
        # Enter password
        password_field = wait_for(
            EC.presence_of_element_located((By.NAME, "password"))
        )
        password_field.clear()
        password_field.send_keys(password)
        
        # Click login button
        login_button = wait_for(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[@data-testid='submit-password']")
            )
        )
        login_button.click()
        
        # Wait for Dice to finish the sign-in response, but do not treat a public job-search
        # page as proof of authentication.
        error_selectors = (
            '[role="alert"]',
            '[data-testid*="error"]',
            '.error-message',
            '.alert-danger',
        )
        transition_deadline = min(overall_deadline - 20, time.monotonic() + 30)
        while time.monotonic() < transition_deadline:
            current_url = (driver.current_url or "").lower()
            if not any(
                marker in current_url for marker in ("/login", "/signin", "/sign-in")
            ):
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
        raise Exception("Dice credentials not found. Please set DICE_USERNAME and DICE_PASSWORD in .env file or provide them as parameters.")
    
    # Navigate to login page
    print("Navigating to Dice login page...")
    driver.get("https://www.dice.com/dashboard/login")
    
    # Set up wait objects with increased timeouts
    short_wait = WebDriverWait(driver, 20)  # Increased timeout
    long_wait = WebDriverWait(driver, 120)  # Much longer timeout for final step

    try:
        # Enter email/username
        print("Entering username...")
        email_field = short_wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_field.clear()
        email_field.send_keys(username)

        # Click continue button
        print("Clicking continue button...")
        continue_button = short_wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='sign-in-button']")))
        continue_button.click()
        time.sleep(3)  # Increased pause to ensure page transitions

        # Enter password
        print("Entering password...")
        password_field = short_wait.until(EC.presence_of_element_located((By.NAME, "password")))
        password_field.clear()
        password_field.send_keys(password)

        # Click login button
        print("Clicking login button...")
        login_button = short_wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='submit-password']")))
        login_button.click()
        
        # Add a longer pause after clicking login
        print("Waiting for login to complete (this may take some time)...")
        time.sleep(10)  # Increased wait time after login click

        # Wait for successful login with multiple verification methods
        print("Verifying login success...")
        try:
            # Method 1: Check for the search form
            long_wait.until(EC.presence_of_element_located((By.XPATH, "//form[@class='flex h-auto w-full flex-row rounded-lg rounded-bl-lg bg-white']")))
            print("Login verified by search form presence!")
            return True
        except Exception as e1:
            print(f"Primary verification method failed: {e1}")
            try:
                # Method 2: Check for any element that would only appear after login
                long_wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'dashboard-header')]")))
                print("Login verified by dashboard header presence!")
                return True
            except Exception as e2:
                print(f"Secondary verification method failed: {e2}")
                try:
                    # Method 3: Check if URL changed to something that indicates successful login
                    current_url = driver.current_url
                    if "dashboard" in current_url or "/home" in current_url or "/jobs" in current_url:
                        print(f"Login verified by URL change to: {current_url}")
                        return True
                    else:
                        print(f"Login verification failed - current URL: {current_url}")
                        # One last attempt - check if any job-related content is visible
                        try:
                            if driver.find_element(By.XPATH, "//div[contains(@class, 'job-cards')]") or \
                               driver.find_element(By.XPATH, "//div[contains(@class, 'search-results')]"):
                                print("Login verified by presence of job-related content!")
                                return True
                        except:
                            pass
                        return False
                except Exception as e3:
                    print(f"URL verification method failed: {e3}")
                    return False

    except Exception as e:
        print(f"Login process failed: {e}")
        return False


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
                if retry != 'y':
                    break
        
        if success:
            print("Credential setup complete! You can now run the main application.")
        else:
            print("Credential setup was not completed. You will need to set up credentials before using the application.")
    
    except Exception as e:
        print(f"An error occurred during setup: {e}")
