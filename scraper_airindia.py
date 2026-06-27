"""
Air India PNR Status Scraper.
Uses Selenium with stealth mode to check flight status on airindia.com

Key design:
  - Same stealth approach as IndiGo scraper (shared driver utility)
  - Targets: https://www.airindia.com/in/en/manage/booking.html
  - Air India form: PNR + Last Name → Retrieve booking
  - Flight numbers: AI XXX pattern (vs IndiGo's 6E XXXX)
"""

import os
import ssl
import time
import logging
import re
import random
from datetime import datetime

# Module-level SSL fix — must run BEFORE any uc/urllib HTTPS calls,
# and must persist across retries (uc.Chrome() can reset things).
ssl._create_default_https_context = ssl._create_unverified_context
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except ImportError:
    pass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

AIRINDIA_HOME = "https://www.airindia.com/in/en.html"
AIRINDIA_URL = "https://www.airindia.com/in/en/manage/booking.html"
MAX_RETRIES = 1

# Rotate User-Agent strings to avoid fingerprint-based blocking
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
]


def _human_delay(min_s=1.0, max_s=3.0):
    """Sleep for a random duration to mimic human behavior."""
    time.sleep(random.uniform(min_s, max_s))


def _is_cloud():
    """Detect if running in cloud/Docker (Render, Railway, etc.)."""
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'


def _fix_ssl():
    """Patch macOS Python SSL so undetected-chromedriver can download its patcher."""
    import ssl
    # env vars don't help urllib — must patch the context factory directly
    ssl._create_default_https_context = ssl._create_unverified_context
    try:
        import certifi
        os.environ['SSL_CERT_FILE'] = certifi.where()
        os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
    except ImportError:
        pass


def _detect_chrome_version():
    """Detect installed Chrome version for uc.Chrome(version_main=...)."""
    import subprocess
    candidates = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium-browser',
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                out = subprocess.check_output([path, '--version'], timeout=5).decode()
                m = re.search(r'(\d+)\.', out)
                if m:
                    return int(m.group(1))
            except Exception:
                continue
    return None


def _create_stealth_driver():
    """Create a Chrome driver with undetected-chromedriver to bypass Imperva WAF."""
    _fix_ssl()

    # Try undetected-chromedriver first (strongest anti-detection)
    try:
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--lang=en-US,en;q=0.9')
        options.add_argument(f'--user-agent={random.choice(USER_AGENTS)}')

        # Local: visible popup window (headless gets fingerprinted by Imperva)
        # Cloud: must be headless (no display)
        if _is_cloud():
            options.add_argument('--headless=new')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            logger.info("Cloud mode: headless + no-sandbox (undetected-chromedriver)")
        else:
            logger.info("Local mode: visible popup window (undetected-chromedriver)")

        # Match installed Chrome version → reduces fingerprint mismatch
        chrome_version = _detect_chrome_version()
        kwargs = {'options': options, 'use_subprocess': False}
        if chrome_version:
            kwargs['version_main'] = chrome_version
            logger.info(f"Using Chrome version_main={chrome_version}")

        driver = uc.Chrome(**kwargs)
        logger.info("Using undetected-chromedriver (Imperva bypass)")
        return driver

    except Exception as e:
        logger.warning(f"undetected-chromedriver failed ({e}), using selenium-stealth fallback")

    # Fallback: regular Selenium + selenium-stealth
    options = Options()
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_argument('--disable-infobars')
    options.add_argument('--lang=en-US,en;q=0.9')
    options.add_argument(f'--user-agent={random.choice(USER_AGENTS)}')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    # Local: visible popup window; Cloud: headless
    if _is_cloud():
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    else:
        logger.info("Local mode: visible popup window (selenium-stealth fallback)")

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        driver = webdriver.Chrome(options=options)

    # Remove webdriver flag
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        '''
    })

    # Apply selenium-stealth for deeper fingerprint masking
    try:
        from selenium_stealth import stealth
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="MacIntel",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True)
        logger.info("selenium-stealth applied successfully")
    except ImportError:
        logger.warning("selenium-stealth not available, using basic stealth only")
    except Exception as e:
        logger.warning(f"selenium-stealth error: {e}")

    return driver


def _dismiss_popups(driver, wait):
    """Try to dismiss cookie consent, search overlays, and other popups."""
    # 1. Cookie consent buttons
    cookie_selectors = [
        'button[id*="accept"]',
        'button[class*="accept"]',
        'button[id*="cookie"]',
        'a[id*="accept"]',
    ]
    for sel in cookie_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            if btn.is_displayed():
                btn.click()
                time.sleep(0.2)
                logger.info(f"Dismissed cookie popup: {sel}")
        except (NoSuchElementException, Exception):
            continue

    time.sleep(0.2)

    # 2. Close the "What are you looking for?" search overlay
    # This overlay blocks the form — look for the X close button
    search_close_selectors = [
        'button[aria-label="Close"]',
        'button[aria-label="close"]',
        '.search-close',
        '.close-search',
        '.modal-close',
        'button[class*="close"]',
        # Close icon in the search overlay (SVG or ×)
        '//button[contains(@class, "close")]',
        '//div[contains(@class, "search")]//button',
    ]
    for sel in search_close_selectors:
        try:
            if sel.startswith('//'):
                btns = driver.find_elements(By.XPATH, sel)
            else:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(0.2)
                    logger.info(f"Closed search/modal overlay: {sel}")
        except (NoSuchElementException, Exception):
            continue

    # 3. Click on body/main content to dismiss any remaining overlay
    try:
        driver.execute_script("document.querySelector('.search-overlay, .overlay, .modal-backdrop')?.remove();")
        logger.info("Removed overlay elements via JS")
    except Exception:
        pass


def _find_and_fill_form(driver, wait, pnr, lastname):
    """
    Find the manage booking form fields and fill them.
    Air India's SPA may use various selectors — we try multiple strategies.
    """
    # Strategy 1: Common input selectors for Air India's manage booking
    pnr_selectors = [
        'input[placeholder*="PNR"]',
        'input[placeholder*="Booking"]',
        'input[placeholder*="booking"]',
        'input[placeholder*="pnr"]',
        'input[name*="pnr"]',
        'input[name*="booking"]',
        'input[id*="pnr"]',
        'input[id*="booking"]',
        'input[data-testid*="pnr"]',
        'input[data-testid*="booking"]',
        'input[aria-label*="PNR"]',
        'input[aria-label*="Booking"]',
        'input[aria-label*="booking reference"]',
    ]

    lastname_selectors = [
        'input[placeholder*="Last"]',
        'input[placeholder*="last"]',
        'input[placeholder*="Surname"]',
        'input[placeholder*="surname"]',
        'input[name*="last"]',
        'input[name*="surname"]',
        'input[id*="last"]',
        'input[id*="surname"]',
        'input[data-testid*="last"]',
        'input[data-testid*="surname"]',
        'input[aria-label*="Last"]',
        'input[aria-label*="last name"]',
        'input[aria-label*="Surname"]',
    ]

    # Wait for form inputs to appear in DOM generally
    try:
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, 'input')) > 1)
    except TimeoutException:
        pass

    # Fill PNR
    pnr_input = None
    for sel in pnr_selectors:
        try:
            pnr_input = driver.find_element(By.CSS_SELECTOR, sel)
            if pnr_input.is_displayed():
                logger.info(f"Found PNR input: {sel}")
                break
            pnr_input = None
        except NoSuchElementException:
            continue

    if not pnr_input:
        # Fallback: find all visible text inputs and use the first one
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input:not([type])')
        visible_inputs = [inp for inp in inputs if inp.is_displayed()]
        if len(visible_inputs) >= 1:
            pnr_input = visible_inputs[0]
            logger.info("PNR input found via fallback (first visible text input)")
        else:
            raise Exception("Could not find PNR input field")

    pnr_input.clear()
    # Type characters with small random delays to mimic human typing
    for char in pnr:
        pnr_input.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))
    _human_delay(0.3, 0.8)

    # Fill Last Name
    lastname_input = None
    for sel in lastname_selectors:
        try:
            lastname_input = driver.find_element(By.CSS_SELECTOR, sel)
            if lastname_input.is_displayed():
                logger.info(f"Found Last Name input: {sel}")
                break
            lastname_input = None
        except NoSuchElementException:
            continue

    if not lastname_input:
        # Fallback: second visible text input
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input:not([type])')
        visible_inputs = [inp for inp in inputs if inp.is_displayed() and inp != pnr_input]
        if visible_inputs:
            lastname_input = visible_inputs[0]
            logger.info("Last Name input found via fallback (second visible text input)")
        else:
            raise Exception("Could not find Last Name input field")

    lastname_input.clear()
    # Type characters with small random delays to mimic human typing
    for char in lastname:
        lastname_input.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))
    _human_delay(0.3, 0.8)

    # Click submit using JavaScript to avoid overlay interception
    submit_btn = None
    # Prioritize the "Submit" text button (visible in Air India UI as red button)
    submit_selectors = [
        '//button[contains(text(), "Submit")]',
        '//button[contains(text(), "submit")]',
        'button[type="submit"]',
        '//button[contains(text(), "Retrieve")]',
        '//button[contains(text(), "Search")]',
        '//button[contains(text(), "Find")]',
        'button[class*="submit"]',
        'button[class*="retrieve"]',
        'button[class*="search"]',
        'button[data-testid*="retrieve"]',
        'button[data-testid*="submit"]',
        'input[type="submit"]',
    ]
    for sel in submit_selectors:
        try:
            if sel.startswith('//'):
                submit_btn = driver.find_element(By.XPATH, sel)
            else:
                submit_btn = driver.find_element(By.CSS_SELECTOR, sel)
            if submit_btn.is_displayed() and submit_btn.is_enabled():
                logger.info(f"Found submit button: {sel}")
                break
            submit_btn = None
        except NoSuchElementException:
            continue

    if not submit_btn:
        raise Exception("Could not find submit/retrieve button")

    _human_delay(0.3, 0.8)
    # Use JavaScript click to bypass any overlapping elements
    driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
    _human_delay(0.3, 0.6)
    driver.execute_script("arguments[0].click();", submit_btn)
    logger.info("Clicked submit button via JavaScript")


def _try_check_pnr(pnr, lastname, attempt=1):
    """
    Single attempt to check Air India PNR status via a fresh browser.
    Returns result dict or raises Exception on failure.
    """
    driver = _create_stealth_driver()
    try:
        logger.info(f"[AI Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        # Go directly to manage booking page (skip homepage — fewer requests = less fingerprinting)
        logger.info("Navigating to manage booking page...")
        driver.get(AIRINDIA_URL)
        _human_delay(5.0, 9.0)  # longer delay to mimic real user

        # Check if page got blocked
        page_text_check = driver.find_element(By.TAG_NAME, 'body').text.lower()
        if 'incapsula incident' in page_text_check or 'request unsuccessful' in page_text_check:
            raise Exception("Imperva WAF blocked the page load — will retry with fresh browser")
        if 'access denied' in page_text_check:
            raise Exception("Access Denied on manage booking — Imperva WAF blocked the request")

        wait = WebDriverWait(driver, 40)

        # Dismiss any popups/cookie banners
        _dismiss_popups(driver, wait)
        _human_delay(0.5, 1.5)

        # Dismiss again in case something re-appeared
        _dismiss_popups(driver, wait)
        _human_delay(0.5, 1.0)

        # Find and fill the form
        _find_and_fill_form(driver, wait, pnr, lastname)

        # Save pre-result screenshot for debugging
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        driver.save_screenshot(os.path.join(screenshots_dir, f'AI_{pnr}_preresult.png'))

        # Dynamically wait for results or secondary modal.
        # NOTE: 'search for a booking' is the secondary modal header, NOT a result.
        # The REAL result is either:
        #   (a) an error banner above the modal ("1 ERROR\nThe payment for..."),
        #   (b) booking details (itinerary, seat, etc.), or
        #   (c) an Imperva block.
        result_keywords = ['error', 'terminal', 'invalid', 'not found', 'cancelled',
                           'confirmed', 'itinerary', 'seat', 'payment failed', 'payment',
                           'booking cannot be found', 'search for a booking']
        start_time = time.time()
        page_text = ""
        while time.time() - start_time < 45:
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text
                text_lower = page_text.lower()
                # Imperva block — bail out fast and let retry handle it
                if 'incapsula incident' in text_lower or 'request unsuccessful' in text_lower:
                    raise Exception("Imperva WAF blocked the API call after form submit")
                if any(kw in text_lower for kw in result_keywords) and len(page_text) > 100:
                    time.sleep(1.5)  # Give it time to fully render (error banner + modal)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                    break
            except Exception as e:
                if 'Imperva' in str(e):
                    raise
            time.sleep(0.5)

        text_lower = page_text.lower()

        # Save screenshot and raw text BEFORE modal handling (for debugging every attempt)
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f'AI_{pnr}_status.png')
        driver.save_screenshot(screenshot_path)
        logger.info(f"Screenshot saved: {screenshot_path}")
        raw_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(raw_dir, f'AI_{pnr}_raw.txt'), 'w') as f:
            f.write(page_text)

        # Check if the secondary modal "Search for a booking" appeared.
        # Air India's flow: first form submit triggers an API call, which returns:
        #   Case A: Error banner ("1 ERROR\n...") + "Search for a booking" modal below
        #   Case B: Just the "Search for a booking" modal (soft block / no response)
        #   Case C: Actual booking details (itinerary page)
        if 'search for a booking' in text_lower and 'continue' in text_lower:
            # Check if there's an error banner ABOVE the modal (Case A)
            # Error banners contain text like "1 ERROR", "The payment for this booking...",
            # "Your booking cannot be found", etc.
            has_error_banner = (
                'error' in text_lower and (
                    'payment' in text_lower or
                    'booking cannot be found' in text_lower or
                    'cannot be found' in text_lower or
                    'try again' in text_lower or
                    'incomplete' in text_lower
                )
            )

            if has_error_banner:
                # Case A: We already have a real result in the error banner.
                # Don't re-submit — just parse the error text we already have.
                logger.info("Secondary modal with ERROR banner detected — parsing error result directly")
                # page_text already contains the error banner text, parse it below.
            else:
                # Case B: Modal appeared with NO error banner.
                # Air India silently rejected our submission (soft block).
                # Try filling the modal form and clicking Continue.
                logger.info("Secondary modal detected WITHOUT error banner — attempting modal form submit...")
                try:
                    _find_and_fill_form(driver, wait, pnr, lastname)
                    # Click the Continue button specifically
                    continue_btns = driver.find_elements(By.XPATH,
                        '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "continue")]')
                    for btn in continue_btns:
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].click();", btn)
                            logger.info("Clicked Continue button on secondary modal")
                            break

                    # Wait for results after modal submit
                    start_time = time.time()
                    while time.time() - start_time < 15:
                        try:
                            page_text = driver.find_element(By.TAG_NAME, 'body').text
                            text_lower = page_text.lower()
                            # Check for Imperva block
                            if 'incapsula incident' in text_lower or 'request unsuccessful' in text_lower:
                                raise Exception("Imperva WAF blocked after modal submit")
                            # Check for error banner appearing
                            if 'error' in text_lower and ('payment' in text_lower or 'cannot be found' in text_lower or 'incomplete' in text_lower):
                                time.sleep(1)
                                page_text = driver.find_element(By.TAG_NAME, 'body').text
                                logger.info("Error banner appeared after modal submit")
                                break
                            # Check for real booking results
                            if any(kw in text_lower for kw in ['itinerary', 'seat', 'confirmed', 'terminal', 'cancelled']):
                                if 'search for a booking' not in text_lower:
                                    time.sleep(1)
                                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                                    logger.info("Booking details page loaded after modal submit")
                                    break
                        except Exception as e:
                            if 'Imperva' in str(e) or 'WAF' in str(e):
                                raise
                        time.sleep(0.5)

                    # Check if we're still stuck on the form (soft block persists)
                    final_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                    if 'search for a booking' in final_text and 'continue' in final_text:
                        if 'error' not in final_text and 'payment' not in final_text and 'cannot be found' not in final_text:
                            logger.warning("Still stuck on Search for a booking form — soft block by Air India")
                            raise Exception("Air India soft-blocked the request (form re-displayed without result). Will retry.")

                except Exception as e:
                    if 'soft-blocked' in str(e).lower() or 'Imperva' in str(e) or 'WAF' in str(e):
                        raise
                    logger.warning(f"Failed to handle secondary modal: {e}")

        # Re-read page_text after modal handling (may have changed)
        page_text = driver.find_element(By.TAG_NAME, 'body').text

        # Save final screenshot after modal handling
        driver.save_screenshot(screenshot_path)
        with open(os.path.join(raw_dir, f'AI_{pnr}_raw.txt'), 'w') as f:
            f.write(page_text)

        # Parse the status
        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}
        text_lower = page_text.lower()

        # Helper: check keyword near PNR in text
        def _keyword_near_pnr(keyword, pnr_code, full_text, window=400):
            fl = full_text.lower()
            kw = keyword.lower()
            pnr_l = pnr_code.lower()
            idx = fl.find(pnr_l)
            if idx == -1:
                return False
            start = max(0, idx - window)
            end = min(len(fl), idx + len(pnr_l) + window)
            region = fl[start:end]
            return kw in region

        # Status detection
        # Payment FAILED → treat as Cancelled (ticket was never issued)
        if any(phrase in text_lower for phrase in [
            'payment failed', 'payment unsuccessful', 'payment has failed',
            'transaction failed', 'payment was not successful',
            'booking has been cancelled due to payment',
            'cancelled due to non-payment',
        ]):
            result['status'] = 'Cancelled'
            result['detail'] = 'Payment failed — booking was not completed. Flight effectively cancelled.'

        # Payment INCOMPLETE → still a chance to complete payment
        elif 'payment for this booking is incomplete' in text_lower or \
             'payment is incomplete' in text_lower:
            result['status'] = 'Payment Pending'
            result['detail'] = 'Payment incomplete — ticket not confirmed. Please complete payment on Air India.'

        elif any(phrase in text_lower for phrase in [
            'invalid', 'not found', 'no booking', 'cannot be found',
            'booking cannot be found', 'try again', 'no record'
        ]):
            result['status'] = 'Cancelled'
            result['detail'] = 'Booking not found on Air India — ticket likely cancelled.'

        elif 'access denied' in text_lower or 'incapsula' in text_lower:
            result['status'] = 'Error'
            result['detail'] = 'Air India website blocked the request. Will retry later.'

        elif _keyword_near_pnr('cancelled', pnr, page_text, window=300) or \
             'cancelled' in text_lower and text_lower.count('cancelled') > 1:
            result['status'] = 'Cancelled'
            result['detail'] = extract_status_detail(page_text, 'cancelled')

        elif _keyword_near_pnr('rescheduled', pnr, page_text, window=300):
            result['status'] = 'Rescheduled'
            result['detail'] = extract_status_detail(page_text, 'rescheduled')

        elif _keyword_near_pnr('delayed', pnr, page_text, window=300):
            result['status'] = 'Delayed'
            result['detail'] = extract_status_detail(page_text, 'delayed')

        elif _keyword_near_pnr('confirmed', pnr, page_text, window=300):
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

        elif _keyword_near_pnr('completed', pnr, page_text, window=300) or \
             _keyword_near_pnr('flown', pnr, page_text, window=300):
            result['status'] = 'Completed'
            result['detail'] = 'Flight has been completed.'

        elif any(kw in text_lower for kw in [
            'confirmed', 'booked', 'itinerary', 'e-ticket',
            'seat selection', 'add-ons', 'check-in', 'checkin'
        ]):
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

        elif 'check-in' in text_lower or 'checkin' in text_lower:
            result['status'] = 'Check-in Open'
            result['detail'] = extract_booking_detail(page_text)

        else:
            # Check if we're still stuck on the "Search for a booking" form
            # (means the submission never went through — soft block)
            if 'search for a booking' in text_lower and 'booking reference' in text_lower and 'continue' in text_lower:
                # Only the form fields are on screen — no real status was returned
                raise Exception("Air India soft-blocked the request (form re-displayed without result). Will retry.")
            result['status'] = 'Checked'
            result['detail'] = page_text[:500] if page_text else 'Could not parse status'

        # Extract flight info for confirmed/valid bookings
        if result['status'] not in ('Not Found', 'Error'):
            result['flight_info'] = extract_flight_info_from_web(page_text, lastname)

        return result

    finally:
        driver.quit()


def extract_flight_info_from_web(text: str, lastname: str) -> dict:
    """Extract flight details from Air India's retrieved booking page text."""
    info = {
        'flight_date': '',
        'route': '',
        'flight_number': '',
        'departure_time': '',
        'arrival_time': '',
        'passenger_name': '',
        'passenger_count': 1,
    }

    lines = text.split('\n')

    # Passenger Count
    # Air India puts "Passenger", "Passengers" and lists "Adult", "Child".
    # Since names are listed with titles, we can count the occurrences of "Adult", "Child", "Infant" or titles.
    # Or count the number of passengers listed under "Passengers".
    # Let's count "Adult", "Child", "Infant" keywords.
    pax_count = 0
    pax_types = re.findall(r'\b(Adult|Child|Infant)\b', text, re.IGNORECASE)
    if pax_types:
        pax_count = len(pax_types)
    else:
        # Fallback: Count titles
        pax_count = len(re.findall(r'\b(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+[A-Za-z]+', text, re.IGNORECASE))
    
    if pax_count > 0:
        info['passenger_count'] = pax_count

    # Passenger name: look for lastname
    for line in lines:
        if lastname.lower() in line.lower():
            # Match "Mr/Ms/Mrs First Last"
            m = re.search(r'(?i)\b(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+([A-Za-z\s]+?\s+' + re.escape(lastname) + r')\b', line)
            if m:
                info['passenger_name'] = m.group(1).strip()
                break
            # Simple match
            m2 = re.search(r'(?i)\b([A-Za-z]+\s+(?:[A-Za-z]+\s+)?' + re.escape(lastname) + r')\b', line)
            if m2:
                info['passenger_name'] = m2.group(1).strip()
                break

    # Flight Number: AI XXX or AI-XXX
    fn_match = re.search(r'(AI[\s-]*\d{1,4})', text)
    if fn_match:
        fn = fn_match.group(1).replace('-', ' ')
        # Normalize to "AI 123"
        fn = re.sub(r'AI\s*', 'AI ', fn)
        info['flight_number'] = fn.strip()

    # Flight Date: "27 Apr 2026" or "27 Apr, 2026" or "2026-04-27"
    date_match = re.search(r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),?\s*(\d{2,4})', text, re.IGNORECASE)
    if date_match:
        try:
            day, mon, year = date_match.group(1), date_match.group(2), date_match.group(3)
            if len(year) == 2:
                year = '20' + year
            dt = datetime.strptime(f'{day} {mon} {year}', '%d %b %Y')
            info['flight_date'] = dt.strftime('%Y-%m-%d')
        except Exception:
            pass

    if not info['flight_date']:
        # Try ISO format
        iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if iso_match:
            info['flight_date'] = iso_match.group(1)

    # Route: 3-letter codes like DEL - BOM or DEL-BOM
    route_match = re.search(r'([A-Z]{3})\s*[-–→]\s*([A-Z]{3})', text)
    if route_match:
        info['route'] = f"{route_match.group(1)}-{route_match.group(2)}"
    else:
        # Look for standalone 3-letter codes on separate lines
        codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)
        if len(codes) >= 2:
            info['route'] = f"{codes[0]}-{codes[1]}"

    # Times: HH:MM format
    times = re.findall(r'\b(\d{2}:\d{2})\b', text)
    if times:
        info['departure_time'] = times[0]
        if len(times) >= 2:
            info['arrival_time'] = times[1]

    return info


def extract_status_detail(text, keyword):
    """Extract detail text around a status keyword."""
    lines = text.split('\n')
    relevant = []
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            start = max(0, i - 1)
            end = min(len(lines), i + 3)
            relevant.extend(lines[start:end])
    return ' | '.join(relevant).strip() if relevant else keyword.capitalize()


def extract_booking_detail(text):
    """Extract booking details from the page text, filtering out website junk."""
    junk_phrases = [
        'cookie', 'privacy', 'terms', 'maharaja club', 'sign in', 'sign up',
        'gift card', 'cargo', 'newsletter', 'download app', 'sitemap',
        'copyright', 'fare rules', 'add-ons', 'route map', 'popular flight',
        'contact us', 'faq', 'feedback', 'e-store', 'exclusive deals',
        'partner airline', 'supplier corner', 'travel agent',
    ]

    lines = text.split('\n')
    details = []
    good_keywords = ['terminal', 'gate', 'boarding', 'seat', 'baggage']

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 3:
            continue
        line_lower = line_stripped.lower()

        if any(junk in line_lower for junk in junk_phrases):
            continue
        if line_stripped.count('|') >= 2:
            continue

        if any(kw in line_lower for kw in good_keywords):
            details.append(line_stripped)

    return ' | '.join(details[:8]) if details else ''


def check_pnr_status(pnr, lastname):
    """
    Check Air India PNR status with retries.
    Each retry creates a fresh browser instance.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _try_check_pnr(pnr, lastname, attempt)
            # If we got Access Denied in the result, treat it as a retryable error
            if result.get('status') == 'Error' and 'blocked' in result.get('detail', '').lower():
                raise Exception(result['detail'])
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"AI Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                # Longer exponential backoff: 30s, 60s, 90s + random jitter
                wait_secs = attempt * 30 + random.randint(5, 15)
                logger.info(f"Waiting {wait_secs}s before retry (longer backoff to avoid WAF)...")
                time.sleep(wait_secs)

    logger.error(f"All {MAX_RETRIES} attempts failed for Air India PNR {pnr}: {last_error}")
    # If all failures were WAF-related, return a friendlier "Check Failed" status
    # so the user sees this is a temporary website issue, not a booking problem
    err_str = str(last_error).lower()
    if any(k in err_str for k in ['imperva', 'incapsula', 'access denied', 'blocked', 'waf', 'soft-block']):
        return {
            'status': 'Check Failed',
            'detail': "Air India website is temporarily blocking automated checks (WAF). Will retry on next scheduled run.",
            'raw_text': '',
        }
    return {
        'status': 'Error',
        'detail': f"Failed after {MAX_RETRIES} attempts: {str(last_error)}",
        'raw_text': '',
    }


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) >= 3:
        pnr = sys.argv[1]
        lastname = sys.argv[2]
        print(f"Checking Air India PNR: {pnr} with last name: {lastname}")
        result = check_pnr_status(pnr, lastname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
        if 'flight_info' in result:
            print(f"Flight Info: {result['flight_info']}")
    else:
        print("Usage: python scraper_airindia.py <PNR> <LASTNAME>")
