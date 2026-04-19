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
import time
import logging
import re
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

AIRINDIA_URL = "https://www.airindia.com/in/en/manage/booking.html"
MAX_RETRIES = 3


def _is_cloud():
    """Detect if running in cloud/Docker (Render, Railway, etc.)."""
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'


def _create_stealth_driver():
    """Create a Chrome driver with selenium-stealth to bypass Imperva/Incapsula bot detection."""
    # Fix SSL cert issue on macOS Python
    import ssl
    import os
    try:
        import certifi
        os.environ['SSL_CERT_FILE'] = certifi.where()
        os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
    except ImportError:
        pass

    # Try undetected-chromedriver first (strongest anti-detection)
    try:
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')

        if _is_cloud():
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            logger.info("Cloud mode: headless + no-sandbox (undetected-chromedriver)")

        driver = uc.Chrome(options=options, use_subprocess=True)
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
    options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    if _is_cloud():
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

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
                time.sleep(0.5)
                logger.info(f"Dismissed cookie popup: {sel}")
        except (NoSuchElementException, Exception):
            continue

    time.sleep(1)

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
                    time.sleep(0.5)
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

    # Fill PNR
    pnr_input = None
    for sel in pnr_selectors:
        try:
            pnr_input = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, sel)))
            logger.info(f"Found PNR input: {sel}")
            break
        except TimeoutException:
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
    pnr_input.send_keys(pnr)
    time.sleep(0.5)

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
    lastname_input.send_keys(lastname)
    time.sleep(0.5)

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

    time.sleep(0.5)
    # Use JavaScript click to bypass any overlapping elements
    driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
    time.sleep(0.3)
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

        driver.get(AIRINDIA_URL)
        time.sleep(8)

        wait = WebDriverWait(driver, 20)

        # Dismiss any popups/cookie banners
        _dismiss_popups(driver, wait)
        time.sleep(2)

        # Dismiss again in case something re-appeared
        _dismiss_popups(driver, wait)
        time.sleep(1)

        # Find and fill the form
        _find_and_fill_form(driver, wait, pnr, lastname)

        # Save pre-result screenshot for debugging
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        driver.save_screenshot(os.path.join(screenshots_dir, f'AI_{pnr}_preresult.png'))

        # Wait for results page to load
        time.sleep(12)

        # Extract page content
        page_text = driver.find_element(By.TAG_NAME, 'body').text

        # Save screenshot for debugging
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f'AI_{pnr}_status.png')
        driver.save_screenshot(screenshot_path)
        logger.info(f"Screenshot saved: {screenshot_path}")

        # Save raw text for debugging
        raw_dir = os.path.dirname(os.path.abspath(__file__))
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
        if any(phrase in text_lower for phrase in [
            'invalid', 'not found', 'no booking', 'cannot be found',
            'booking cannot be found', 'try again', 'no record'
        ]):
            result['status'] = 'Not Found'
            result['detail'] = 'PNR not found or invalid. Please verify the PNR and last name.'

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

        elif 'completed' in text_lower or 'flown' in text_lower:
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
        'passenger_name': ''
    }

    lines = text.split('\n')

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
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"AI Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = attempt * 10
                logger.info(f"Waiting {wait_secs}s before retry...")
                time.sleep(wait_secs)

    logger.error(f"All {MAX_RETRIES} attempts failed for Air India PNR {pnr}: {last_error}")
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
