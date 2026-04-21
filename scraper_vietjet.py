"""
VietJet Air PNR Status Scraper.
Uses Selenium with stealth mode to check flight status on vietjetair.com

Key design:
  - Same stealth approach as Air India scraper (undetected-chromedriver)
  - Target: https://www.vietjetair.com/en/my/search-booking
  - VietJet form: Booking Reference + First Name + Last Name
  - Flight numbers: VJ XXX pattern
"""

import os
import time
import logging
import re
import random
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

VIETJET_URL = "https://www.vietjetair.com/en/my/search-booking"
MAX_RETRIES = 3


def _human_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))


def _is_cloud():
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'


def _fix_ssl():
    """Patch macOS Python SSL so undetected-chromedriver can download its patcher."""
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    try:
        import certifi
        os.environ['SSL_CERT_FILE'] = certifi.where()
        os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
    except ImportError:
        pass


def _create_stealth_driver():
    """Create undetected-chromedriver instance."""
    _fix_ssl()

    try:
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--lang=en-US,en;q=0.9')

        if _is_cloud():
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            logger.info("Cloud mode: headless + no-sandbox")

        driver = uc.Chrome(options=options, use_subprocess=False)
        logger.info("Using undetected-chromedriver")
        return driver

    except Exception as e:
        logger.warning(f"undetected-chromedriver failed ({e}), falling back to standard Selenium")

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-first-run')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    if _is_cloud():
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        driver = webdriver.Chrome(options=options)

    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    })
    return driver


def _accept_cookies(driver, wait):
    """Accept VietJet's cookie consent dialog (MUI Dialog)."""
    # VietJet shows a MUI Dialog with an Accept/OK button — must click it before interacting with the form
    cookie_xpaths = [
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "ACCEPT")]',
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "AGREE")]',
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "OK")]',
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "GOT IT")]',
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "ALLOW")]',
    ]
    cookie_css = [
        'button[id*="accept"]', 'button[class*="accept"]',
        'button[id*="cookie"]', 'button[class*="cookie"]',
        'button[id*="agree"]', 'button[class*="agree"]',
    ]

    # Wait a moment for cookie dialog to appear
    time.sleep(2)

    clicked = False
    for xpath in cookie_xpaths:
        try:
            btns = driver.find_elements(By.XPATH, xpath)
            for btn in btns:
                if btn.is_displayed() and btn.is_enabled():
                    driver.execute_script("arguments[0].click();", btn)
                    logger.info(f"Accepted cookies via XPATH: {xpath} — text: '{btn.text}'")
                    time.sleep(1)
                    clicked = True
                    break
            if clicked:
                break
        except Exception:
            continue

    if not clicked:
        for sel in cookie_css:
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    if btn.is_displayed() and btn.is_enabled():
                        driver.execute_script("arguments[0].click();", btn)
                        logger.info(f"Accepted cookies via CSS: {sel}")
                        time.sleep(1)
                        clicked = True
                        break
                if clicked:
                    break
            except Exception:
                continue

    if not clicked:
        # Last resort: remove the MUI Dialog overlay from DOM
        try:
            removed = driver.execute_script("""
                var dialogs = document.querySelectorAll('.MuiDialog-root, .MuiDialog-container, [class*="MuiDialog"]');
                var backdrops = document.querySelectorAll('.MuiBackdrop-root, [class*="MuiBackdrop"]');
                var count = 0;
                dialogs.forEach(el => { el.remove(); count++; });
                backdrops.forEach(el => { el.remove(); count++; });
                document.body.style.overflow = 'auto';
                return count;
            """)
            logger.info(f"Removed {removed} MUI dialog/backdrop elements via JS")
        except Exception as e:
            logger.warning(f"Could not remove cookie dialog: {e}")


def _dismiss_popups(driver):
    """Dismiss any remaining popups after cookie acceptance."""
    selectors = [
        'button[aria-label="Close"]', 'button[aria-label="close"]',
        '.close-button', '[data-testid*="close"]',
    ]
    for sel in selectors:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(0.3)
        except Exception:
            continue


def _type_into(element, text, driver):
    """Clear and type text character by character with human-like delays."""
    element.click()
    _human_delay(0.2, 0.5)
    # Clear via JS first, then send chars
    driver.execute_script("arguments[0].value = '';", element)
    driver.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles: true}));", element)
    element.clear()
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))
    _human_delay(0.2, 0.5)


def _find_and_fill_form(driver, wait, pnr, firstname, lastname):
    """Find and fill VietJet's search booking form."""
    # Wait for at least some inputs to appear
    try:
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, 'input')) >= 2)
    except TimeoutException:
        pass

    _human_delay(1.0, 2.0)

    # --- Booking Reference ---
    booking_selectors = [
        'input[placeholder*="booking" i]',
        'input[placeholder*="reference" i]',
        'input[placeholder*="PNR" i]',
        'input[name*="booking" i]',
        'input[name*="reference" i]',
        'input[name*="pnr" i]',
        'input[id*="booking" i]',
        'input[id*="reference" i]',
        'input[aria-label*="booking" i]',
        'input[aria-label*="reference" i]',
    ]

    booking_input = None
    for sel in booking_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                booking_input = el
                logger.info(f"Found booking input: {sel}")
                break
        except NoSuchElementException:
            continue

    if not booking_input:
        visible = [i for i in driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input:not([type])') if i.is_displayed()]
        if visible:
            booking_input = visible[0]
            logger.info("Booking input found via fallback (first visible text input)")
        else:
            raise Exception("Could not find booking reference input")

    _type_into(booking_input, pnr, driver)

    # --- First Name ---
    first_selectors = [
        'input[placeholder*="first" i]',
        'input[placeholder*="given" i]',
        'input[name*="first" i]',
        'input[name*="given" i]',
        'input[id*="first" i]',
        'input[id*="given" i]',
        'input[aria-label*="first" i]',
        'input[aria-label*="given" i]',
    ]

    first_input = None
    for sel in first_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed() and el != booking_input:
                first_input = el
                logger.info(f"Found first name input: {sel}")
                break
        except NoSuchElementException:
            continue

    if not first_input:
        visible = [i for i in driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input:not([type])') if i.is_displayed() and i != booking_input]
        if visible:
            first_input = visible[0]
            logger.info("First name input found via fallback")

    if first_input:
        _type_into(first_input, firstname, driver)

    # --- Last Name ---
    last_selectors = [
        'input[placeholder*="last" i]',
        'input[placeholder*="surname" i]',
        'input[name*="last" i]',
        'input[name*="surname" i]',
        'input[id*="last" i]',
        'input[id*="surname" i]',
        'input[aria-label*="last" i]',
        'input[aria-label*="surname" i]',
    ]

    last_input = None
    for sel in last_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed() and el not in (booking_input, first_input):
                last_input = el
                logger.info(f"Found last name input: {sel}")
                break
        except NoSuchElementException:
            continue

    if not last_input:
        visible = [i for i in driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input:not([type])') if i.is_displayed() and i not in (booking_input, first_input)]
        if visible:
            last_input = visible[0]
            logger.info("Last name input found via fallback")

    if last_input:
        _type_into(last_input, lastname, driver)

    # --- Submit ---
    submit_selectors = [
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "SEARCH")]',
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "FIND")]',
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "RETRIEVE")]',
        '//button[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "SUBMIT")]',
        'button[type="submit"]',
        'button[class*="search"]',
        'button[class*="submit"]',
    ]

    submit_btn = None
    for sel in submit_selectors:
        try:
            if sel.startswith('//'):
                btn = driver.find_element(By.XPATH, sel)
            else:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
            if btn.is_displayed() and btn.is_enabled():
                submit_btn = btn
                logger.info(f"Found submit button: {sel}")
                break
        except NoSuchElementException:
            continue

    if not submit_btn:
        raise Exception("Could not find search/submit button")

    _human_delay(0.3, 0.8)
    driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
    _human_delay(0.2, 0.5)
    driver.execute_script("arguments[0].click();", submit_btn)
    logger.info("Clicked submit button via JavaScript")


def _try_check_pnr(pnr, firstname, lastname, attempt=1):
    """Single attempt to check VietJet PNR. Returns result dict or raises."""
    driver = _create_stealth_driver()
    try:
        logger.info(f"[VJ Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        driver.get(VIETJET_URL)
        _human_delay(4.0, 7.0)

        page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        if 'access denied' in page_text or 'blocked' in page_text:
            raise Exception("VietJet website blocked the request")

        wait = WebDriverWait(driver, 25)

        # Accept cookie consent dialog first — it blocks form interaction
        _accept_cookies(driver, wait)
        _dismiss_popups(driver)
        _human_delay(1.0, 2.0)

        _find_and_fill_form(driver, wait, pnr, firstname, lastname)

        # Save pre-result screenshot
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        driver.save_screenshot(os.path.join(screenshots_dir, f'VJ_{pnr}_preresult.png'))

        # Wait for results
        result_keywords = ['flight', 'booking', 'confirmed', 'cancelled', 'not found',
                           'invalid', 'departure', 'arrival', 'passenger', 'itinerary', 'error']
        start_time = time.time()
        page_text = ""
        while time.time() - start_time < 20:
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text
                text_lower = page_text.lower()
                if any(kw in text_lower for kw in result_keywords) and len(page_text) > 200:
                    time.sleep(1)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                    break
            except Exception:
                pass
            time.sleep(0.5)

        # Save result screenshot and raw text
        driver.save_screenshot(os.path.join(screenshots_dir, f'VJ_{pnr}_status.png'))
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f'VJ_{pnr}_raw.txt'), 'w') as f:
            f.write(page_text)
        logger.info(f"Screenshot and raw text saved for {pnr}")

        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}
        text_lower = page_text.lower()

        # Status detection
        if any(phrase in text_lower for phrase in [
            'not found', 'no booking', 'cannot be found', 'invalid',
            'no result', 'booking not found', 'does not exist',
        ]):
            result['status'] = 'Cancelled'
            result['detail'] = 'Booking not found on VietJet — ticket likely cancelled.'

        elif 'access denied' in text_lower or 'blocked' in text_lower:
            result['status'] = 'Error'
            result['detail'] = 'VietJet website blocked the request. Will retry later.'

        elif any(phrase in text_lower for phrase in ['cancelled', 'canceled']):
            result['status'] = 'Cancelled'
            result['detail'] = _extract_around_keyword(page_text, 'cancel')

        elif 'rescheduled' in text_lower or 'schedule change' in text_lower:
            result['status'] = 'Rescheduled'
            result['detail'] = _extract_around_keyword(page_text, 'reschedule')

        elif 'delayed' in text_lower:
            result['status'] = 'Delayed'
            result['detail'] = _extract_around_keyword(page_text, 'delay')

        elif any(phrase in text_lower for phrase in [
            'confirmed', 'booked', 'itinerary', 'e-ticket',
            'departure', 'arrival', 'passenger', 'seat',
        ]):
            result['status'] = 'Confirmed'
            result['detail'] = _extract_booking_detail(page_text)

        elif 'completed' in text_lower or 'flown' in text_lower:
            result['status'] = 'Completed'
            result['detail'] = 'Flight has been completed.'

        else:
            result['status'] = 'Checked'
            result['detail'] = page_text[:500] if page_text else 'Could not parse status'

        if result['status'] not in ('Error', 'Cancelled'):
            result['flight_info'] = _extract_flight_info(page_text, firstname, lastname)

        return result

    finally:
        driver.quit()


def _extract_around_keyword(text, keyword, window=300):
    """Extract text around a keyword."""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return keyword.capitalize()
    start = max(0, idx - 50)
    end = min(len(text), idx + window)
    return text[start:end].strip()


def _extract_booking_detail(text):
    """Extract clean booking info lines."""
    junk = ['cookie', 'privacy', 'terms', 'sign in', 'sign up', 'newsletter',
            'download app', 'copyright', 'sitemap', 'contact us', 'faq']
    lines = text.split('\n')
    good = ['departure', 'arrival', 'terminal', 'gate', 'seat', 'baggage', 'passenger', 'flight']
    details = []
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue
        ll = stripped.lower()
        if any(j in ll for j in junk):
            continue
        if any(g in ll for g in good):
            details.append(stripped)
    return ' | '.join(details[:8]) if details else ''


def _extract_flight_info(text, firstname, lastname):
    """Extract flight details from VietJet result page."""
    info = {
        'flight_date': '',
        'route': '',
        'flight_number': '',
        'departure_time': '',
        'arrival_time': '',
        'passenger_name': '',
    }

    # Flight number: VJ followed by digits
    fn_match = re.search(r'(VJ[\s-]?\d{1,4})', text, re.IGNORECASE)
    if fn_match:
        fn = re.sub(r'VJ\s*', 'VJ ', fn_match.group(1).upper())
        info['flight_number'] = fn.strip()

    # Date: "28 Apr 2026" or "24/04/2026" or ISO
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
        # DD/MM/YYYY format (VietJet)
        dmy = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
        if dmy:
            try:
                info['flight_date'] = f"{dmy.group(3)}-{dmy.group(2)}-{dmy.group(1)}"
            except Exception:
                pass
    if not info['flight_date']:
        iso = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if iso:
            info['flight_date'] = iso.group(1)

    # Route: 3-letter airport codes
    route = re.search(r'([A-Z]{3})\s*[-–→]\s*([A-Z]{3})', text)
    if route:
        info['route'] = f"{route.group(1)}-{route.group(2)}"

    # Times HH:MM
    times = re.findall(r'\b(\d{2}:\d{2})\b', text)
    if times:
        info['departure_time'] = times[0]
        if len(times) >= 2:
            info['arrival_time'] = times[1]

    # Passenger name
    full_name = f"{firstname} {lastname}".strip()
    if full_name.lower() in text.lower():
        info['passenger_name'] = full_name.title()
    elif lastname.lower() in text.lower():
        m = re.search(r'(?i)\b([A-Za-z]+\s+' + re.escape(lastname) + r')\b', text)
        if m:
            info['passenger_name'] = m.group(1).strip()

    return info


def check_pnr_status(pnr, lastname, firstname=''):
    """
    Check VietJet PNR status with retries.
    Each retry creates a fresh browser instance.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _try_check_pnr(pnr, firstname, lastname, attempt)
            if result.get('status') == 'Error' and 'blocked' in result.get('detail', '').lower():
                raise Exception(result['detail'])
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"VJ Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = attempt * 30 + random.randint(5, 15)
                logger.info(f"Waiting {wait_secs}s before retry...")
                time.sleep(wait_secs)

    logger.error(f"All {MAX_RETRIES} attempts failed for VietJet PNR {pnr}: {last_error}")
    return {
        'status': 'Error',
        'detail': f"Failed after {MAX_RETRIES} attempts: {str(last_error)}",
        'raw_text': '',
    }


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) >= 4:
        pnr, firstname, lastname = sys.argv[1], sys.argv[2], sys.argv[3]
        print(f"Checking VietJet PNR: {pnr} | {firstname} {lastname}")
        result = check_pnr_status(pnr, lastname, firstname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
        if 'flight_info' in result:
            print(f"Flight Info: {result['flight_info']}")
    else:
        print("Usage: python scraper_vietjet.py <PNR> <FIRSTNAME> <LASTNAME>")
