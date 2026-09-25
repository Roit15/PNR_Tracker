"""
Indigo PNR Status Scraper.
Uses Selenium with stealth mode to check flight status on goindigo.in

Key design:
  - Uses Selenium (not Playwright) — Indigo's Akamai Bot Manager blocks Playwright
  - Stealth mode: disables automation flags so Indigo thinks it's a real user
  - Each PNR gets a FRESH browser instance (no cookies/cache from previous PNR)
  - Global rate limiter enforces minimum gap between IndiGo requests (defeats Akamai pattern detection)
  - Cookie/privacy banner is explicitly dismissed before form interaction
  - Session-expired (Akamai bot-challenge) detected via URL + text → automatic retry
  - Retries up to 3 times on failure with exponential back-off + jitter
"""

import os
import platform
import ssl
import time
import signal
import logging
import tempfile
import shutil
import threading
import random

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
from selenium.webdriver.common.action_chains import ActionChains

logger = logging.getLogger(__name__)

INDIGO_URL = "https://www.goindigo.in/account/my-bookings.html"
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Global rate limiter — enforces a minimum gap between IndiGo requests.
# Akamai's bot detection pattern-matches rapid sequential browser sessions.
# ---------------------------------------------------------------------------
_INDIGO_LOCK = threading.Lock()
_INDIGO_LAST_REQUEST = 0.0
_INDIGO_MIN_INTERVAL = 12  # seconds

def _indigo_rate_limit():
    """Enforce minimum gap between IndiGo scrape calls (global, thread-safe)."""
    global _INDIGO_LAST_REQUEST
    with _INDIGO_LOCK:
        now = time.time()
        elapsed = now - _INDIGO_LAST_REQUEST
        if elapsed < _INDIGO_MIN_INTERVAL:
            wait = _INDIGO_MIN_INTERVAL - elapsed + random.uniform(1, 4)
            logger.info(f"Rate limiting IndiGo: waiting {wait:.1f}s before next request")
            time.sleep(wait)
        _INDIGO_LAST_REQUEST = time.time()


def _is_cloud():
    """Detect if running in cloud/Docker (Render, Railway, etc.)."""
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'


def _fix_uc_binary():
    """Ensure the UC chromedriver binary is the correct architecture.

    On Apple Silicon Macs, UC 3.5.5 downloads an x86_64 chromedriver binary
    which causes 'Bad CPU type in executable' ([Errno 86]).

    Fix:
    1. If the binary exists and is wrong arch → replace it with arm64 from Chrome for Testing.
    2. Make the binary read-only (chmod 555) so UC's patcher cannot overwrite it.
    3. On non-Mac or non-arm64 systems, this is a no-op.
    """
    import stat
    import subprocess

    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        return  # Only needed on Apple Silicon Macs

    uc_dir = os.path.expanduser(
        '~/Library/Application Support/undetected_chromedriver'
    )
    uc_binary = os.path.join(uc_dir, 'undetected_chromedriver')

    # Check if existing binary is correct arch
    if os.path.exists(uc_binary):
        try:
            # Make writable first so we can check properly
            try:
                os.chmod(uc_binary, 0o644)
            except Exception:
                pass
            result = subprocess.run(['file', uc_binary], capture_output=True, text=True)
            if 'arm64' in result.stdout:
                # Binary is correct — lock it read-only so UC patcher cannot overwrite
                os.chmod(uc_binary, 0o444)
                logger.debug("arm64 UC binary confirmed, locked read-only")
                return
            else:
                logger.info(f"UC binary is wrong arch ({result.stdout.strip()}) — replacing with arm64")
        except Exception as e:
            logger.debug(f"Could not check UC binary arch: {e}")
            return

    # Binary is missing or wrong arch — download the correct arm64 one
    try:
        import urllib.request
        import zipfile
        import io

        # Get Chrome version to match chromedriver version
        chrome_result = subprocess.run(
            ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '--version'],
            capture_output=True, text=True
        )
        chrome_ver = chrome_result.stdout.strip().split()[-1]  # e.g. "153.0.8010.53"

        url = f"https://storage.googleapis.com/chrome-for-testing-public/{chrome_ver}/mac-arm64/chromedriver-mac-arm64.zip"
        logger.info(f"Downloading arm64 chromedriver {chrome_ver} for UC...")

        with urllib.request.urlopen(url, timeout=30) as resp:
            zip_data = resp.read()

        os.makedirs(uc_dir, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for member in zf.namelist():
                if member.endswith('chromedriver') and '__MACOSX' not in member:
                    with zf.open(member) as src, open(uc_binary, 'wb') as dst:
                        dst.write(src.read())
                    break

        os.chmod(uc_binary, 0o444)  # read-only for everyone — prevents UC patcher overwrite
        # Remove quarantine bit
        subprocess.run(['xattr', '-d', 'com.apple.quarantine', uc_binary],
                       capture_output=True)
        logger.info(f"Installed arm64 chromedriver {chrome_ver} at {uc_binary} (read-only)")
    except Exception as e:
        logger.warning(f"Could not install arm64 chromedriver: {e}")




# ---------------------------------------------------------------------------
# Rotating user-agents — reduces Akamai fingerprinting across sessions
# ---------------------------------------------------------------------------
_USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
]


def _kill_driver(driver):
    """Aggressively kill Chrome driver + ALL child processes + temp profile dir."""
    if driver is None:
        return

    tmp_profile = getattr(driver, '_tmp_profile', None)

    chrome_pid = getattr(driver, 'browser_pid', None)
    service_pid = None
    try:
        if hasattr(driver, 'service') and hasattr(driver.service, 'process'):
            service_pid = driver.service.process.pid
    except Exception:
        pass

    try:
        driver.quit()
        logger.debug("driver.quit() succeeded")
    except Exception as e:
        logger.debug(f"driver.quit() failed: {e}")

    pids_to_kill = [p for p in [chrome_pid, service_pid] if p]
    try:
        import psutil
        for pid in pids_to_kill:
            try:
                parent = psutil.Process(pid)
                for child in parent.children(recursive=True):
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
    except ImportError:
        for pid in pids_to_kill:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    if tmp_profile and os.path.exists(tmp_profile):
        try:
            shutil.rmtree(tmp_profile, ignore_errors=True)
            logger.debug(f"Removed temp profile: {tmp_profile}")
        except Exception as e:
            logger.debug(f"Could not remove temp profile {tmp_profile}: {e}")


def _create_stealth_driver():
    """Create a Chrome driver with CDP + selenium-stealth to bypass Akamai bot detection.

    Strategy (macOS SIP note):
    - undetected-chromedriver is NOT used on macOS: it byte-patches the chromedriver binary,
      which invalidates the code signature and causes macOS Gatekeeper to SIGKILL the process.
    - Instead we use Selenium 4's native CDP to inject webdriver-hiding JS before page load,
      combined with selenium-stealth for deeper fingerprint patching.
    - Each PNR check gets a fresh isolated user-data-dir (tempfile) to prevent Akamai from
      correlating sessions across multiple checks.
    """
    ua = random.choice(_USER_AGENTS)
    tmp_profile = tempfile.mkdtemp(prefix='indigo_profile_')

    options = Options()
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--lang=en-US,en;q=0.9')
    options.add_argument(f'--user-data-dir={tmp_profile}')
    options.add_argument(f'--user-agent={ua}')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    if _is_cloud():
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-software-rasterizer')
        logger.info(f"Cloud mode: headful (Xvfb), ua={ua[:45]}...")
    else:
        options.add_argument('--headless=new')
        logger.info(f"Local mode: headless, ua={ua[:45]}...")

    driver = webdriver.Chrome(options=options)
    driver._tmp_profile = tmp_profile

    # CDP: inject stealth JS before ANY page script runs (most effective placement)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            // Hide webdriver flag
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // Spoof chrome runtime (expected by Akamai)
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
            // Spoof plugins (real browser has 3+)
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            // Spoof languages
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            // Remove automation-related properties
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        '''
    })

    # selenium-stealth: deeper WebGL, hairline, and other fingerprint patches
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
        logger.info("Applied CDP + selenium-stealth")
    except ImportError:
        logger.info("Applied CDP stealth (selenium-stealth not available)")

    return driver


def _dismiss_cookie_banner(driver, timeout=4):
    """Dismiss IndiGo's cookie/privacy consent banner.

    From DOM inspection (confirmed):
    IndiGo uses <a> tags with class="cc-btn cc-allow cc-btn-format" — NOT <button> elements.
    The banner is fixed at the bottom and intercepts clicks on the 'Get Started' button.
    """
    # Primary: confirmed CSS selectors from DOM inspection
    primary_selectors = [
        'a.cc-btn.cc-allow',      # IndiGo cc-cookie-banner (confirmed from DOM)
        'a[class*="cc-allow"]',   # class variant
        '.cc-allow',              # any element with cc-allow class
    ]
    for sel in primary_selectors:
        try:
            btn = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
            )
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.8)
            logger.info(f"Cookie banner dismissed ({sel})")
            return True
        except Exception:
            continue

    # XPath fallbacks for any element with Accept All text
    for xpath in [
        '//a[normalize-space(.)="Accept All"]',
        '//button[normalize-space(.)="Accept All"]',
        '//*[@role="button" and normalize-space(.)="Accept All"]',
    ]:
        try:
            btn = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.8)
            logger.info(f"Cookie banner dismissed via XPath: {xpath}")
            return True
        except Exception:
            continue

    logger.debug("No cookie banner found (or already dismissed)")
    return False


def _is_session_expired(driver):
    """Detect Akamai's session-expired / bot-challenge page.

    Only returns True for definitive Akamai challenge patterns.
    'Something went wrong' is too generic — IndiGo shows it on normal error pages.
    """
    try:
        url = driver.current_url.lower()
        if any(p in url for p in ['ak_challenge', 'akamai', 'sessionexpir']):
            logger.warning(f"Session expired detected via URL: {url[:100]}")
            return True
    except Exception:
        pass

    try:
        text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        challenge_phrases = [
            "you've been away",
            "session expired",
            "looks like your session",
        ]
        if any(p in text for p in challenge_phrases):
            logger.warning("Session expired detected via page text")
            return True
    except Exception:
        pass

    return False


def _try_check_pnr(pnr, lastname_or_email, attempt=1):
    """
    Single attempt to check PNR status via a fresh browser.
    Returns result dict or raises Exception on failure.
    """
    # Enforce global rate limit before creating the browser
    _indigo_rate_limit()

    driver = _create_stealth_driver()
    try:
        logger.info(f"[Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        # Navigate to My Bookings page
        driver.get(INDIGO_URL)
        time.sleep(random.uniform(5, 8))

        # Early session-expired check (Akamai may block before page loads)
        if _is_session_expired(driver):
            raise Exception("IndiGo session expired immediately after page load (Akamai block)")

        # Dismiss cookie banner BEFORE interacting with the form
        _dismiss_cookie_banner(driver, timeout=5)

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

        # Dismiss cookie banner again — it sometimes re-appears after user interaction
        _dismiss_cookie_banner(driver, timeout=2)

        # Click Get Started
        get_started = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[title="Get Started"]'))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", get_started)
        time.sleep(random.uniform(0.5, 1.0))

        # Try ActionChains first (more human-like), fall back to JS click
        clicked = False
        try:
            ActionChains(driver).move_to_element(get_started).pause(0.3).click().perform()
            clicked = True
        except Exception:
            pass
        if not clicked:
            driver.execute_script("arguments[0].click();", get_started)
            logger.debug("Used JS click fallback for Get Started button")

        # Check 5 seconds in: are we still stuck on the input form?
        time.sleep(5)
        quick_check = driver.find_element(By.TAG_NAME, 'body').text
        if 'pnr / booking reference' in quick_check.lower() and 'get started' in quick_check.lower():
            logger.warning("Still on form after first click — dismissing banner and retrying")
            # Try dismissing the cookie banner one more time (it may have blocked the click)
            _dismiss_cookie_banner(driver, timeout=3)
            time.sleep(0.5)
            try:
                btn = driver.find_element(By.CSS_SELECTOR, 'button[title="Get Started"]')
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)
                logger.info("JS retry click sent")
            except Exception as e:
                logger.warning(f"JS retry click also failed: {e}")

        # Wait for the loading screen / spinner to fully clear after click
        time.sleep(8)

        # Smart wait: poll until results appear (max 25s)
        page_text = ""
        for i in range(25):
            time.sleep(1)
            page_text = driver.find_element(By.TAG_NAME, 'body').text
            text_lower = page_text.lower()

            # Detect Akamai session-expired challenge immediately
            if _is_session_expired(driver):
                raise Exception(
                    f"IndiGo session expired (Akamai bot-challenge) after {i+1}s. "
                    "Will retry with a fresh browser."
                )

            if any(kw in text_lower for kw in ['invalid', 'not found', 'no booking', 'error']):
                logger.info(f"Got error response after {i+1}s")
                break
            if len(page_text) > 1000 and any(kw in text_lower for kw in [
                'terminal information', 'flight number', 'departure', 'confirmed',
                'retrieve another booking', '6e prime', 'add-ons',
            ]):
                logger.info(f"Got flight data after {i+1}s")
                break
        else:
            logger.info("Timed out waiting for results (25s), proceeding with current page")

        # Final definitive read + session-expired check
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        if _is_session_expired(driver):
            raise Exception(
                "IndiGo session expired (Akamai bot-challenge) on final page. "
                "Will retry with a fresh browser."
            )

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
        def _keyword_near_pnr(keyword, pnr_code, full_text, window=300):
            """Return True if keyword appears within `window` chars of the PNR code."""
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

        # Safety check: stuck on input form
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

        elif _keyword_near_pnr('confirmed', pnr, page_text, window=200):
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

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

    for line in lines:
        if lastname.lower() in line.lower():
            m1 = re.search(r"(?i)\b(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+([A-Za-z\s]+?\s+" + re.escape(lastname) + r")\b", line)
            if m1:
                passenger_name = m1.group(1).strip()
                break
            m2 = re.search(r"(?i)\bHello\s+([A-Za-z\s]+?\s+" + re.escape(lastname) + r")\b", line)
            if m2:
                passenger_name = m2.group(1).strip()
                break

    if not passenger_name:
        for line in lines:
            if lastname.lower() in line.lower():
                m3 = re.search(r"(?i)\b([A-Za-z]+\s+(?:[A-Za-z]+\s+)?" + re.escape(lastname) + r")\b", line)
                if m3:
                    val = m3.group(1).strip()
                    if not val.lower().startswith("hello "):
                        passenger_name = val
                        break

    passenger_count = 1
    for line in lines:
        m_pax = re.search(r'(?i)(\d+)\s+Pax', line)
        if m_pax:
            passenger_count = int(m_pax.group(1))
            break

    date_range_match = re.search(
        r'(\d{1,2})\s+([A-Za-z]{3}),?\s*(\d{2,4})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]{3}),?\s*(\d{2,4})',
        text
    )

    codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)
    flight_numbers = re.findall(r'(6E\s*\d{3,4})', text)
    flight_numbers = [fn.replace(' ', '') for fn in flight_numbers]
    times = re.findall(r'^(\d{2}:\d{2})$', text, re.MULTILINE)

    def _parse_short_date(day, month, year_str):
        yr = year_str
        if len(yr) == 2:
            yr = "20" + yr
        try:
            dt = datetime.strptime(f"{day} {month} {yr}", '%d %b %Y')
            return dt.strftime('%Y-%m-%d')
        except:
            return ''

    if date_range_match and len(codes) >= 4:
        date1 = _parse_short_date(date_range_match.group(1), date_range_match.group(2), date_range_match.group(3))
        date2 = _parse_short_date(date_range_match.group(4), date_range_match.group(5), date_range_match.group(6))
        seg1 = {
            'flight_date': date1, 'route': f"{codes[0]}-{codes[1]}",
            'flight_number': flight_numbers[0] if len(flight_numbers) >= 1 else '',
            'departure_time': times[0] if len(times) >= 1 else '',
            'arrival_time': times[1] if len(times) >= 2 else '',
            'passenger_name': passenger_name or '', 'passenger_count': passenger_count,
        }
        seg2 = {
            'flight_date': date2, 'route': f"{codes[2]}-{codes[3]}",
            'flight_number': flight_numbers[1] if len(flight_numbers) >= 2 else '',
            'departure_time': times[2] if len(times) >= 3 else '',
            'arrival_time': times[3] if len(times) >= 4 else '',
            'passenger_name': passenger_name or '', 'passenger_count': passenger_count,
        }
        return [seg1, seg2]

    info = {
        'flight_date': '', 'route': '', 'flight_number': '',
        'departure_time': '', 'arrival_time': '',
        'passenger_name': passenger_name or '', 'passenger_count': passenger_count,
    }

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

    if flight_numbers:
        info['flight_number'] = flight_numbers[0]

    if len(codes) >= 2:
        info['route'] = f"{codes[0]}-{codes[1]}"
        for i in range(len(codes) - 1):
            if codes[i] != codes[i+1]:
                info['route'] = f"{codes[i]}-{codes[i+1]}"
                break

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
        if any(junk in line_lower for junk in junk_phrases):
            continue
        if line_stripped.count('|') >= 2:
            continue
        if any(kw in line_lower for kw in good_keywords):
            details.append(line_stripped)

    return ' | '.join(details[:8]) if details else ''


def check_pnr_status(pnr, lastname_or_email):
    """
    Check PNR status with retries.
    Each retry creates a fresh browser instance with exponential back-off + jitter.
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
                # Exponential back-off with jitter to defeat Akamai rate/pattern detection
                base_wait = attempt * 15
                jitter = random.uniform(0, 10)
                wait_secs = base_wait + jitter
                logger.info(f"Waiting {wait_secs:.1f}s before retry (attempt {attempt}/{MAX_RETRIES})...")
                time.sleep(wait_secs)

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
