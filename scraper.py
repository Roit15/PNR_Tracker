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

        # --- Helper: check if keyword appears near the PNR badge/status area ---
        # IndiGo pages have ads, promos, T&C text that can contain keywords
        # like "rescheduled" or "cancelled". We only trust these if they appear
        # in proximity to the PNR number in the page text.
        def _keyword_near_pnr(keyword, pnr_code, full_text, window=300):
            """Return True if keyword appears within `window` chars of the PNR code."""
            fl = full_text.lower()
            kw = keyword.lower()
            pnr_l = pnr_code.lower()
            idx = fl.find(pnr_l)
            if idx == -1:
                return False
            # Check a window around the PNR
            start = max(0, idx - window)
            end = min(len(fl), idx + len(pnr_l) + window)
            region = fl[start:end]
            return kw in region

        if 'invalid' in text_lower or 'not found' in text_lower or 'no booking' in text_lower:
            result['status'] = 'Not Found'
            result['detail'] = 'PNR not found or invalid. Please verify the PNR and last name.'

        elif 'status of your payment' in text_lower or ('pending' in text_lower and 'pay now' in text_lower):
            result['status'] = 'Pending Payment'
            result['detail'] = 'Payment is pending or being processed.'

        # --- Check Confirmed FIRST ---
        # IndiGo shows a clear ✅ Confirmed badge next to the PNR.
        # If we see "confirmed" near the PNR, trust that over loose keyword matches.
        elif _keyword_near_pnr('confirmed', pnr, page_text, window=200):
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

        # --- Negative statuses: only trust if near PNR or on standalone line ---
        elif _keyword_near_pnr('cancelled', pnr, page_text, window=200) or \
             'cancelled\n' in text_lower or '\ncancelled\n' in text_lower or \
             text_lower.count('cancelled') > 2:
            result['status'] = 'Cancelled'
            result['detail'] = extract_status_detail(page_text, 'cancelled')

        elif _keyword_near_pnr('rescheduled', pnr, page_text, window=200):
            result['status'] = 'Rescheduled'
            result['detail'] = extract_status_detail(page_text, 'rescheduled')

        elif _keyword_near_pnr('delayed', pnr, page_text, window=200):
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
            # Fallback: Indigo shows add-ons / nav for confirmed bookings
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

        elif 'check-in' in text_lower or 'checkin' in text_lower:
            result['status'] = 'Check-in Open'
            result['detail'] = extract_booking_detail(page_text)

        else:
            result['status'] = 'Checked'
            result['detail'] = page_text[:500] if page_text else 'Could not parse status'

        if result['status'] not in ('Not Found', 'Error', 'Pending Payment'):
            result['flight_info'] = extract_flight_info_from_web(page_text, lastname_or_email)

        return result

    finally:
        driver.quit()


def extract_flight_info_from_web(text: str, lastname: str) -> dict:
    """Extract flight date, number, route, and full name from IndiGo's retrieved page text."""
    import re
    from datetime import datetime
    info = {
        'flight_date': '',
        'route': '',
        'flight_number': '',
        'departure_time': '',
        'arrival_time': '',
        'passenger_name': ''
    }
    
    lines = text.split('\n')
    passenger_name = None

    # Extractor: Passenger Name
    # Try looking for "Mr. First Last" or "Hello First Last"
    for line in lines:
        if lastname.lower() in line.lower():
            # 1. Match title Prefix
            m1 = re.search(r"(?i)\b(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+([A-Za-z\s]+?\s+" + re.escape(lastname) + r")\b", line)
            if m1:
                passenger_name = m1.group(1).strip()
                break
            # 2. Match "Hello"
            m2 = re.search(r"(?i)\bHello\s+([A-Za-z\s]+?\s+" + re.escape(lastname) + r")\b", line)
            if m2:
                passenger_name = m2.group(1).strip()
                break

    # If no title matched, try simple 1-2 words before Last Name
    if not passenger_name:
        for line in lines:
            if lastname.lower() in line.lower():
                m3 = re.search(r"(?i)\b([A-Za-z]+\s+(?:[A-Za-z]+\s+)?" + re.escape(lastname) + r")\b", line)
                if m3:
                    val = m3.group(1).strip()
                    if not val.lower().startswith("hello "): # Avoid matching "Hello First Last" again
                        passenger_name = val
                        break
    
    if passenger_name:
        info['passenger_name'] = passenger_name

    # 1. Flight Date
    # Looking for "27 Apr, 26" or "27 Apr 2026"
    date_match = re.search(r'(\d{1,2}\s+[A-Za-z]{3},?\s*\d{2,4})', text)
    if date_match:
        try:
            date_str = date_match.group(1).replace(',', '')
            parts = date_str.split()
            if len(parts[-1]) == 2:
                parts[-1] = "20" + parts[-1]
            date_str = " ".join(parts)
            dt = datetime.strptime(date_str, '%d %b %Y')
            info['flight_date'] = dt.strftime('%Y-%m-%d')
        except:
            pass

    # 2. Flight Number
    fn_match = re.search(r'(6E\s*\d{3,4})', text)
    if fn_match:
        info['flight_number'] = fn_match.group(1).replace(' ', '')
        
    # 3. Route
    # Look for standalone 3-letter codes at start of lines (e.g. DPS \n DEL)
    codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)
    if len(codes) >= 2:
        info['route'] = f"{codes[0]}-{codes[1]}"
        
    # 4. Times
    # Look for "19:10" at start of line
    times = re.findall(r'^(\d{2}:\d{2})$', text, re.MULTILINE)
    if times:
        info['departure_time'] = times[0]
        info['arrival_time'] = times[-1]
        
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
        'update contact', 'travel time', 'baggage per adult',
        'baggage per child', 'baggage', 'flight details', 'pnr:',
        'departure flight', 'return flight',
    ]

    lines = text.split('\n')
    details = []
    good_keywords = ['terminal', 'gate', 'boarding']

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 3:
            continue
        line_lower = line_stripped.lower()

        # Skip junk lines
        if any(junk in line_lower for junk in junk_phrases):
            continue

        # Skip breadcrumb/nav-style lines (many short fragments)
        if line_stripped.count('|') >= 2:
            continue

        # Keep lines with useful flight keywords
        if any(kw in line_lower for kw in good_keywords):
            details.append(line_stripped)

    return ' | '.join(details[:8]) if details else ''


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
