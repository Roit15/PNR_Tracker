"""
Indigo PNR Status Scraper.
Uses Selenium with stealth mode to check flight status on goindigo.in

Key design:
  - Uses Selenium (not Playwright) — Indigo's Akamai Bot Manager blocks Playwright
  - Stealth mode: disables automation flags so Indigo thinks it's a real user
  - Each PNR gets a FRESH browser instance (no cookies/cache from previous PNR)
  - Retries up to 3 times on failure with increasing wait
"""

import os
import time
import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

INDIGO_URL = "https://www.goindigo.in/account/my-bookings.html"
MAX_RETRIES = 3


def _is_cloud():
    """Detect if running in cloud/Docker (Render, Railway, etc.)."""
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'


def _create_stealth_driver():
    """Create a Chrome driver with stealth settings to bypass Akamai bot detection."""
    options = Options()
    options.add_argument('--window-size=1280,720')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    # Cloud/Docker: Chrome needs these to run in container
    if _is_cloud():
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        logger.info("Cloud mode: headless + no-sandbox + stealth user-agent")

    # Use webdriver-manager to auto-install matching chromedriver
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        # Fallback: system chromedriver
        driver = webdriver.Chrome(options=options)

    # Remove webdriver flag from navigator
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
    })

    return driver


def _try_check_pnr(pnr, lastname_or_email, attempt=1):
    """
    Single attempt to check PNR status via a fresh browser.
    Returns result dict or raises Exception on failure.
    """
    driver = _create_stealth_driver()
    try:
        logger.info(f"[Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        # Navigate to My Bookings page
        driver.get(INDIGO_URL)
        time.sleep(8)

        # Wait for PNR input to be visible
        wait = WebDriverWait(driver, 20)
        pnr_input = wait.until(
            EC.visibility_of_element_located((By.NAME, 'pnr-booking-ref'))
        )

        # Fill PNR
        pnr_input.clear()
        pnr_input.send_keys(pnr)
        time.sleep(0.5)

        # Fill Last Name / Email
        email_input = driver.find_element(By.NAME, 'email-last-name')
        email_input.clear()
        email_input.send_keys(lastname_or_email)
        time.sleep(1)

        # Click Get Started
        get_started = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[title="Get Started"]'))
        )
        time.sleep(0.5)
        get_started.click()

        # Wait for results to load
        time.sleep(8)

        # Extract page content
        page_text = driver.find_element(By.TAG_NAME, 'body').text

        # Save screenshot for debugging
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f'{pnr}_status.png')
        driver.save_screenshot(screenshot_path)
        logger.info(f"Screenshot saved: {screenshot_path}")

        # Parse the status
        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}
        text_lower = page_text.lower()

        if 'invalid' in text_lower or 'not found' in text_lower or 'no booking' in text_lower:
            result['status'] = 'Not Found'
            result['detail'] = 'PNR not found or invalid. Please verify the PNR and last name.'

        elif 'cancelled' in text_lower:
            result['status'] = 'Cancelled'
            result['detail'] = extract_status_detail(page_text, 'cancelled')

        elif 'rescheduled' in text_lower:
            result['status'] = 'Rescheduled'
            result['detail'] = extract_status_detail(page_text, 'rescheduled')

        elif 'delayed' in text_lower:
            result['status'] = 'Delayed'
            result['detail'] = extract_status_detail(page_text, 'delayed')

        elif 'completed' in text_lower or 'flown' in text_lower:
            result['status'] = 'Completed'
            result['detail'] = 'Flight has been completed.'

        elif any(kw in text_lower for kw in [
            'confirmed', 'booked', 'retrieve another booking',
            '6e prime', 'add-ons', 'add - ons', 'quickboard',
            'fast forward', 'baggage'
        ]):
            # Indigo shows add-ons and "Retrieve Another Booking" for confirmed bookings
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

        elif 'check-in' in text_lower or 'checkin' in text_lower:
            result['status'] = 'Check-in Open'
            result['detail'] = extract_booking_detail(page_text)

        else:
            result['status'] = 'Checked'
            result['detail'] = page_text[:500] if page_text else 'Could not parse status'

        return result

    finally:
        driver.quit()


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
    # Junk phrases from Indigo's navigation/UI that should never appear in detail
    junk_phrases = [
        'split pnr', 'cancel flight', 'change flight', 'change seat',
        'web check-in', 'customer.experience', 'check flight status',
        'add-ons', 'add - ons', '6e prime', '6e seat', '6e eats',
        'fast forward', 'quickboard', 'lounge', 'zero cancellation',
        'additional piece', 'sports equipment', 'travel assistance',
        'retrieve another booking', 'most popular', 'get 20%',
        'personalized bundle', 'chat with us', 'need help',
        'more inf', 'popular', 'about any issue', 'if any charges',
        'promptly refund', 'download app', 'newsletter',
    ]

    lines = text.split('\n')
    details = []
    good_keywords = ['flight', 'departure', 'arrival', 'terminal', 'gate',
                     'seat', 'baggage', 'status', 'pnr', 'date', 'time',
                     'passenger', 'boarding']

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 3:
            continue
        line_lower = line_stripped.lower()

        # Skip junk lines
        if any(junk in line_lower for junk in junk_phrases):
            continue

        # Keep lines with useful flight keywords
        if any(kw in line_lower for kw in good_keywords):
            details.append(line_stripped)

    return ' | '.join(details[:8]) if details else 'Booking confirmed'


def check_pnr_status(pnr, lastname_or_email):
    """
    Check PNR status with retries.
    Each retry creates a fresh browser instance.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _try_check_pnr(pnr, lastname_or_email, attempt)
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = attempt * 10
                logger.info(f"Waiting {wait_secs}s before retry...")
                time.sleep(wait_secs)

    # All retries exhausted
    logger.error(f"All {MAX_RETRIES} attempts failed for PNR {pnr}: {last_error}")
    return {
        'status': 'Error',
        'detail': f"Failed after {MAX_RETRIES} attempts: {str(last_error)}",
        'raw_text': '',
    }


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        pnr = sys.argv[1]
        lastname = sys.argv[2]
        print(f"Checking PNR: {pnr} with last name: {lastname}")
        result = check_pnr_status(pnr, lastname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
    else:
        print("Usage: python scraper.py <PNR> <LASTNAME>")
