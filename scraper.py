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
import ssl
import time
import signal
import logging

# Module-level SSL fix — persistent across retries
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

logger = logging.getLogger(__name__)

INDIGO_URL = "https://www.goindigo.in/account/my-bookings.html"
MAX_RETRIES = 3


def _is_cloud():
    """Detect if running in cloud/Docker (Render, Railway, etc.)."""
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'
import random

def _kill_driver(driver):
    """Aggressively kill Chrome driver and ALL child processes to prevent orphans."""
    if driver is None:
        return

    # Step 1: Try to get the Chrome process PID before quitting
    chrome_pid = getattr(driver, 'browser_pid', None)
    service_pid = None
    try:
        if hasattr(driver, 'service') and hasattr(driver.service, 'process'):
            service_pid = driver.service.process.pid
    except Exception:
        pass

    # Step 2: Try driver.quit() first (graceful shutdown)
    try:
        driver.quit()
        logger.debug("driver.quit() succeeded")
    except Exception as e:
        logger.debug(f"driver.quit() failed: {e}")

    # Step 3: Kill the Chrome process tree via psutil (if available)
    pids_to_kill = [p for p in [chrome_pid, service_pid] if p]
    try:
        import psutil
        for pid in pids_to_kill:
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                try:
                    parent.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            except psutil.NoSuchProcess:
                pass
        logger.debug(f"Killed Chrome process tree via psutil (pids={pids_to_kill})")
        return
    except ImportError:
        pass

    # Step 4: Fallback — kill PIDs directly with SIGKILL
    for pid in pids_to_kill:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _create_stealth_driver():
    """Create a Chrome driver with advanced stealth to bypass Akamai bot detection.
    
    Strategy:
    1. Primary: undetected-chromedriver (patches Chrome binary to remove automation flags)
    2. Fallback: standard Selenium + selenium-stealth (JS-level patching)
    """
    # Try undetected-chromedriver first (best for Akamai)
    try:
        import undetected_chromedriver as uc
        
        uc_options = uc.ChromeOptions()
        uc_options.add_argument('--start-maximized')
        uc_options.add_argument('--window-size=1920,1080')
        uc_options.add_argument('--no-first-run')
        uc_options.add_argument('--no-default-browser-check')
        uc_options.add_argument('--lang=en-US,en;q=0.9')
        
        if _is_cloud():
            # Run headful inside Xvfb instead of headless to prevent undetected-chromedriver crashes
            uc_options.add_argument('--no-sandbox')
            uc_options.add_argument('--disable-dev-shm-usage')
            logger.info("Cloud mode: headful (Xvfb) + undetected-chromedriver")
        else:
            uc_options.add_argument('--headless=new')
            logger.info("Local mode: headless (undetected-chromedriver)")
        
        driver = uc.Chrome(options=uc_options, version_main=153, use_subprocess=True)
        logger.info("Using undetected-chromedriver for IndiGo/Singapore")
        return driver
    except Exception as e:
        logger.warning(f"undetected-chromedriver failed ({e}), falling back to selenium-stealth")
    
    # Fallback: standard Selenium + selenium-stealth
    options = Options()
    options.add_argument('--start-maximized')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_argument('--lang=en-US,en;q=0.9')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    if _is_cloud():
        # Run headful inside Xvfb
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        logger.info("Cloud mode: headful (Xvfb) + stealth fallback")
    else:
        logger.info("Local mode: visible popup window (stealth fallback)")

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        driver = webdriver.Chrome(options=options)

    # Apply selenium-stealth for JS-level anti-detection
    try:
        from selenium_stealth import stealth
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        logger.info("Applied selenium-stealth patches")
    except ImportError:
        # Minimal JS patching if selenium-stealth not available
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
        time.sleep(random.uniform(5, 8))

        # Wait for PNR input to be visible
        wait = WebDriverWait(driver, 40)
        pnr_input = wait.until(
            EC.visibility_of_element_located((By.NAME, 'pnr-booking-ref'))
        )

        # Fill PNR (human-like: type each character with random delay)
        pnr_input.click()
        time.sleep(0.3)
        pnr_input.clear()
        for char in pnr:
            pnr_input.send_keys(char)
            time.sleep(random.uniform(0.08, 0.2))
        time.sleep(random.uniform(0.5, 1.0))

        # Fill Last Name / Email (human-like)
        email_input = driver.find_element(By.NAME, 'email-last-name')
        email_input.click()
        time.sleep(0.3)
        email_input.clear()
        for char in lastname_or_email:
            email_input.send_keys(char)
            time.sleep(random.uniform(0.08, 0.2))
        time.sleep(random.uniform(0.8, 1.5))

        # Click Get Started
        get_started = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[title="Get Started"]'))
        )
        # Scroll it to the center to avoid cookie banners covering it
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", get_started)
        time.sleep(random.uniform(0.5, 1.0))
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).move_to_element(get_started).pause(0.3).click().perform()
        except Exception:
            get_started.click()

        # Mandatory wait for the loading screen/spinner to clear
        time.sleep(7)

        # Smart wait: poll until results appear (max 20s)
        page_text = ""
        for i in range(20):
            time.sleep(1)
            page_text = driver.find_element(By.TAG_NAME, 'body').text
            text_lower = page_text.lower()
            
            # The loading screen might contain generic keywords. 
            # We require the text to be somewhat substantial or contain specific error phrases.
            if any(kw in text_lower for kw in ['invalid', 'not found', 'no booking', 'error']):
                logger.info(f"Got error response after {i+1}s")
                break
            # A valid itinerary page usually has much more text than the base page
            if len(page_text) > 1000 and any(kw in text_lower for kw in ['terminal information', 'flight number', 'departure', 'confirmed']):
                logger.info(f"Got flight data after {i+1}s")
                break
        else:
            logger.info("Timed out waiting for results (20s), proceeding with current page")

        # Re-read final page content
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

        # Safety check: If we are still on the base page (form didn't submit)
        if 'pnr / booking reference' in text_lower and 'get started' in text_lower:
            result['status'] = 'Error'
            result['detail'] = 'Stuck on loading page. Form did not submit successfully.'
            return result

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

        elif _keyword_near_pnr('completed', pnr, page_text, window=200) or \
             _keyword_near_pnr('flown', pnr, page_text, window=200):
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
        _kill_driver(driver)


def extract_flight_info_from_web(text: str, lastname: str) -> list:
    """Extract flight segments from IndiGo's retrieved page text.

    Returns a list of segment dicts (usually 1, but 2 for round-trip PNRs).
    Each dict has: flight_date, route, flight_number, departure_time, arrival_time, passenger_name.
    """
    import re
    from datetime import datetime

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
                    if not val.lower().startswith("hello "):
                        passenger_name = val
                        break

    # Extractor: Passenger Count
    # IndiGo often writes "2 Pax" or similar.
    passenger_count = 1
    for line in lines:
        m_pax = re.search(r'(?i)(\d+)\s+Pax', line)
        if m_pax:
            passenger_count = int(m_pax.group(1))
            break

    # --- Detect round-trip: date range like "25 Jun, 26-02 Jul, 26" or "25 Jun, 26 - 02 Jul, 26" ---
    date_range_match = re.search(
        r'(\d{1,2})\s+([A-Za-z]{3}),?\s*(\d{2,4})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]{3}),?\s*(\d{2,4})',
        text
    )

    # --- Airport codes: standalone 3-letter codes on their own lines ---
    codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)

    # --- Flight numbers: all 6E XXXX ---
    flight_numbers = re.findall(r'(6E\s*\d{3,4})', text)
    flight_numbers = [fn.replace(' ', '') for fn in flight_numbers]

    # --- Times: standalone HH:MM ---
    times = re.findall(r'^(\d{2}:\d{2})$', text, re.MULTILINE)

    def _parse_short_date(day, month, year_str):
        """Parse a date like (25, 'Jun', '26') -> '2026-06-25'."""
        yr = year_str
        if len(yr) == 2:
            yr = "20" + yr
        try:
            dt = datetime.strptime(f"{day} {month} {yr}", '%d %b %Y')
            return dt.strftime('%Y-%m-%d')
        except:
            return ''

    # --- ROUND TRIP: 4 codes (BOM CMB CMB BOM) + date range ---
    if date_range_match and len(codes) >= 4:
        date1 = _parse_short_date(date_range_match.group(1), date_range_match.group(2), date_range_match.group(3))
        date2 = _parse_short_date(date_range_match.group(4), date_range_match.group(5), date_range_match.group(6))

        route1 = f"{codes[0]}-{codes[1]}"
        route2 = f"{codes[2]}-{codes[3]}"

        seg1 = {
            'flight_date': date1,
            'route': route1,
            'flight_number': flight_numbers[0] if len(flight_numbers) >= 1 else '',
            'departure_time': times[0] if len(times) >= 1 else '',
            'arrival_time': times[1] if len(times) >= 2 else '',
            'passenger_name': passenger_name or '',
            'passenger_count': passenger_count,
        }
        seg2 = {
            'flight_date': date2,
            'route': route2,
            'flight_number': flight_numbers[1] if len(flight_numbers) >= 2 else '',
            'departure_time': times[2] if len(times) >= 3 else '',
            'arrival_time': times[3] if len(times) >= 4 else '',
            'passenger_name': passenger_name or '',
            'passenger_count': passenger_count,
        }
        return [seg1, seg2]

    # --- SINGLE LEG (original behavior) ---
    info = {
        'flight_date': '',
        'route': '',
        'flight_number': '',
        'departure_time': '',
        'arrival_time': '',
        'passenger_name': passenger_name or '',
        'passenger_count': passenger_count,
    }

    # Flight Date
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

    # Flight Number
    if flight_numbers:
        info['flight_number'] = flight_numbers[0]

    # Route
    if len(codes) >= 2:
        info['route'] = f"{codes[0]}-{codes[1]}"
        # Find first pair of distinct codes to avoid bugs like 'DPS-DPS'
        for i in range(len(codes) - 1):
            if codes[i] != codes[i+1]:
                info['route'] = f"{codes[i]}-{codes[i+1]}"
                break

    # Times
    if times:
        info['departure_time'] = times[0]
        info['arrival_time'] = times[-1]

    return [info]


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
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    if len(sys.argv) >= 3:
        pnr = sys.argv[1]
        lastname = sys.argv[2]
        print(f"Checking PNR: {pnr} with last name: {lastname}")
        result = check_pnr_status(pnr, lastname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
    else:
        print("Usage: python scraper.py <PNR> <LASTNAME>")
