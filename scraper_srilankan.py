"""
SriLankan Airlines PNR Status Scraper.
Uses Playwright with stealth to fill the manage booking form on srilankan.com

Key design:
  - Uses www.srilankan.com/en_uk/plan-and-book/manage-your-booking (NOT digital.srilankan.com)
  - The main site passes WAF; digital.srilankan.com gets blocked by Incapsula
  - Form has: Last Name + Booking Reference -> blue arrow submit button
  - After submit, redirects to digital.srilankan.com with valid cookies
  - Playwright replaces the Node.js Puppeteer subprocess
"""

import os
import time
import logging
import re
import random
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

SRILANKAN_MANAGE_URL = "https://www.srilankan.com/en_uk/plan-and-book/manage-your-booking"
MAX_RETRIES = 3

# Limit to 1 concurrent SriLankan check — CDP shares one Chrome instance
_cdp_semaphore = threading.Semaphore(1)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

BLOCKED_DOMAINS = [
    'google-analytics.com', 'googletagmanager.com', 'facebook.net',
    'doubleclick.net', 'hotjar.com', 'newrelic.com', 'nr-data.net',
    'sentry.io', 'segment.com', 'mixpanel.com', 'amplitude.com',
]


def _is_cloud():
    """Detect if running in cloud/Docker."""
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'


def _human_delay(min_s=1.0, max_s=3.0):
    """Sleep for a random duration to mimic human behavior."""
    time.sleep(random.uniform(min_s, max_s))


def _dismiss_cookies(page):
    """Try to dismiss cookie consent banner."""
    cookie_selectors = [
        'text=Accept All', 'text=Accept all',
        'button:has-text("Accept All")', 'button:has-text("Accept")',
        'a:has-text("Accept All")', 'a:has-text("Accept")',
        'button[id*="accept"]', 'button[class*="accept"]',
    ]
    for sel in cookie_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=3000)
                logger.info(f"Dismissed cookie banner: {sel}")
                _human_delay(0.5, 1.0)
                return True
        except Exception:
            continue
    return False


def _try_check_pnr(pnr, lastname, attempt=1):
    """Single attempt to check SriLankan Airlines PNR using form on main site."""
    from playwright.sync_api import sync_playwright
    import chrome_launcher

    logger.info(f"[SriLankan Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

    chrome_launcher.ensure_chrome_running()
    pw = sync_playwright().start()
    browser = None
    context = None
    try:
        try:
            # Connect to existing Chrome running with --remote-debugging-port=9224
            browser = pw.chromium.connect_over_cdp("http://localhost:9224")
        except Exception as e:
            pw.stop()
            raise Exception(
                "Could not connect to Chrome on port 9224. "
                "Ensure Chrome is installed."
            ) from e

        # We use the default context of the running browser, and just create a new tab.
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        # Block analytics/tracking
        def _route_handler(route):
            url = route.request.url
            if any(domain in url for domain in BLOCKED_DOMAINS):
                route.abort()
            else:
                route.fallback()

        page.route("**/*", _route_handler)

        # Step 0: Warm up booking domains to establish Incapsula cookies
        # The form submits to book.srilankan.com which redirects to digital.srilankan.com
        logger.info("Warming up book.srilankan.com to establish cookies...")
        try:
            page.goto('https://book.srilankan.com/', wait_until='domcontentloaded', timeout=20000)
            _human_delay(2.0, 3.0)
            warmup_body = page.inner_text('body')
            logger.info(f"book.srilankan.com warmup: {len(warmup_body)} chars")
        except Exception as e:
            logger.warning(f"book.srilankan.com warmup failed: {e}")

        # Also warm up digital.srilankan.com
        logger.info("Warming up digital.srilankan.com...")
        try:
            page.goto('https://digital.srilankan.com/', wait_until='domcontentloaded', timeout=20000)
            _human_delay(2.0, 3.0)
            warmup2 = page.inner_text('body')
            logger.info(f"digital.srilankan.com warmup: {len(warmup2)} chars")
        except Exception as e:
            logger.warning(f"digital.srilankan.com warmup failed: {e}")

        _human_delay(1.0, 2.0)

        # Step 1: Load the main manage booking page (bypasses WAF)
        logger.info("Loading srilankan.com manage booking page...")
        page.goto(SRILANKAN_MANAGE_URL, wait_until='domcontentloaded', timeout=45000)
        _human_delay(4.0, 7.0)

        # Check for WAF block
        body_text = page.inner_text('body').lower()
        if 'incapsula incident' in body_text or 'access denied' in body_text or 'request unsuccessful' in body_text:
            raise Exception("WAF blocked the main site page load")

        # Dismiss cookie banner if present
        _dismiss_cookies(page)
        _human_delay(1.0, 2.0)

        # Step 2: Fill the manage booking form using exact element IDs
        # Desktop form (RefX Flow): #lastname2refx, #bookref2refx, #btnMybSearch
        # Hidden fields: #REC_LOC, #DIRECT_RETRIEVE_LASTNAME
        # Form: #form_booking_manager -> posts to book.srilankan.com
        logger.info("Looking for manage booking form fields...")

        # Check that the RefX flow form is visible
        refx_flow = page.locator('#refxFlow')
        if refx_flow.count() == 0 or not refx_flow.is_visible(timeout=3000):
            logger.warning("RefX flow form not visible, checking for alternatives...")

        # Find the exact Last Name input
        lastname_input = page.locator('#lastname2refx')
        if not lastname_input.is_visible(timeout=3000):
            # Fallback to mobile form
            lastname_input = page.locator('#lastname2')
            if not lastname_input.is_visible(timeout=2000):
                raise Exception("Could not find Last Name input (#lastname2refx or #lastname2)")
            logger.info("Using mobile form #lastname2")
        else:
            logger.info("Found desktop form #lastname2refx")

        # Find the exact Booking Reference input
        pnr_input = page.locator('#bookref2refx')
        if not pnr_input.is_visible(timeout=2000):
            pnr_input = page.locator('#bookref2')
            if not pnr_input.is_visible(timeout=2000):
                raise Exception("Could not find Booking Reference input (#bookref2refx or #bookref2)")
            logger.info("Using mobile form #bookref2")
        else:
            logger.info("Found desktop form #bookref2refx")

        # Fill the form with human-like typing
        logger.info(f"Filling Last Name: {lastname}")
        lastname_input.scroll_into_view_if_needed()
        _human_delay(0.5, 1.0)
        lastname_input.click()
        _human_delay(0.3, 0.6)
        lastname_input.fill('')
        lastname_input.type(lastname, delay=random.uniform(50, 100))
        _human_delay(0.5, 1.0)

        logger.info(f"Filling Booking Reference: {pnr}")
        pnr_input.click()
        _human_delay(0.3, 0.6)
        pnr_input.fill('')
        pnr_input.type(pnr.upper(), delay=random.uniform(50, 100))
        _human_delay(0.5, 1.0)

        # Also populate the hidden fields that the JS function normally sets
        page.evaluate(f'''() => {{
            let recLoc = document.getElementById("REC_LOC");
            if (recLoc) recLoc.value = "{pnr.upper()}";
            let directLastname = document.getElementById("DIRECT_RETRIEVE_LASTNAME");
            if (directLastname) directLastname.value = "{lastname}";
        }}''')
        logger.info("Set hidden fields REC_LOC and DIRECT_RETRIEVE_LASTNAME")

        # Click the submit button (blue chevron-right)
        submit_btn = page.locator('#btnMybSearch')
        if not submit_btn.is_visible(timeout=2000):
            submit_btn = page.locator('#btnMybSearchDX')
            if not submit_btn.is_visible(timeout=2000):
                # Fallback: try submitting the form via JS
                logger.info("No submit button visible, submitting form via JS...")
                page.evaluate('''() => {
                    let form = document.getElementById("form_booking_manager");
                    if (form) form.submit();
                }''')
            else:
                logger.info("Using DX submit button")
                submit_btn.click(timeout=5000)
        else:
            _human_delay(0.3, 0.8)
            submit_btn.scroll_into_view_if_needed()
            _human_delay(0.3, 0.5)
            submit_btn.click(timeout=5000)
            logger.info("Clicked #btnMybSearch submit button")

        # Step 3: Wait for navigation to digital.srilankan.com or result page
        logger.info("Waiting for result page...")
        try:
            page.wait_for_load_state('networkidle', timeout=30000)
        except Exception:
            pass

        # Wait for SPA to render (may redirect to digital.srilankan.com)
        page_text = ''
        for i in range(15):
            _human_delay(3.0, 5.0)
            try:
                page_text = page.inner_text('body')
            except Exception:
                page_text = ''

            # Check if WAF blocked after redirect
            text_lower = page_text.lower()
            if 'incapsula incident' in text_lower or 'request unsuccessful' in text_lower:
                # Check if this is the final page or just a redirect challenge
                if len(page_text) < 500:
                    logger.info(f"WAF challenge detected (attempt {i+1}/15), waiting...")
                    continue
                else:
                    raise Exception("WAF blocked the result page")

            if 'access denied' in text_lower and len(page_text) < 500:
                raise Exception("Access Denied on result page")

            # Check for meaningful content
            if len(page_text) > 300:
                # Skip loading screens
                if 'please stand by' in text_lower or 'getting everything ready' in text_lower:
                    logger.info(f"Loading screen detected (attempt {i+1}/15)...")
                    continue

                # Check for actual result content
                result_keywords = ['confirmed', 'your flight', 'booking details',
                                   'services summary', 'not found', 'cannot be found',
                                   'cancelled', 'something went wrong', 'error',
                                   'passenger', 'economy', 'business', 'nonstop']
                if any(kw in text_lower for kw in result_keywords):
                    logger.info(f"Result page rendered ({len(page_text)} chars)")
                    break

            # Also check iframes
            for frame in page.frames:
                try:
                    frame_text = frame.inner_text('body')
                    if len(frame_text) > len(page_text):
                        page_text = frame_text
                except Exception:
                    pass

            if len(page_text) > 500:
                text_lower = page_text.lower()
                if any(kw in text_lower for kw in ['confirmed', 'your flight', 'not found', 'cancelled']):
                    logger.info(f"Result found in frame ({len(page_text)} chars)")
                    break

        # Take screenshot
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        page.screenshot(path=os.path.join(screenshots_dir, f'UL_{pnr}_result.png'), full_page=True)
        logger.info("Screenshot saved")

        # Save raw text
        raw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'UL_{pnr}_raw.txt')
        with open(raw_path, 'w') as f:
            f.write(page_text)

        # Parse the result
        if not page_text or len(page_text) < 50:
            raise Exception("No content rendered after form submission")

        text_lower = page_text.lower()

        # Check for WAF block in final content
        if ('incident id' in text_lower or 'request unsuccessful' in text_lower) and len(page_text) < 500:
            raise Exception("WAF blocked the final result")

        if 'access denied' in text_lower and len(page_text) < 500:
            raise Exception("Access Denied on final result")

        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}

        # Status detection
        if 'something went wrong' in text_lower:
            result['status'] = 'Not Found'
            result['detail'] = 'Booking could not be retrieved -- PNR may be expired or invalid'

        elif any(kw in text_lower for kw in ['not found', 'does not match',
                                              'cannot be found', 'no booking',
                                              'unable to retrieve', 'no record',
                                              'invalid booking']):
            result['status'] = 'Not Found'
            result['detail'] = 'PNR not found or invalid on SriLankan Airlines.'

        elif any(kw in text_lower for kw in ['status: confirmed', 'your flight',
                                              'booking details', 'services summary',
                                              'one way flight', 'return flight']):
            result['status'] = 'Confirmed'
            result['detail'] = _extract_booking_detail(page_text)

        elif 'confirmed' in text_lower and ('flight' in text_lower or 'passenger' in text_lower):
            result['status'] = 'Confirmed'
            result['detail'] = _extract_booking_detail(page_text)

        elif 'cancelled' in text_lower:
            result['status'] = 'Cancelled'
            result['detail'] = 'Booking appears to be cancelled.'

        elif any(kw in text_lower for kw in ['completed', 'flown', 'past trip']):
            result['status'] = 'Completed'
            result['detail'] = 'Flight has been completed.'

        elif 'check-in' in text_lower or 'checkin' in text_lower:
            result['status'] = 'Check-in Open'
            result['detail'] = _extract_booking_detail(page_text)

        elif 'manage your booking' in text_lower and 'unlimited changes' in text_lower:
            # Still on the form page -- submission didn't go through
            raise Exception("Form submission failed -- still on manage booking page")

        else:
            result['status'] = 'Checked'
            result['detail'] = page_text[:500] if page_text else 'Could not parse status'

        # Extract flight info for valid bookings
        if result['status'] not in ('Error', 'Not Found'):
            result['flight_info'] = _extract_flight_info(page_text, lastname)

        return result

    finally:
        try:
            # page might not be defined if it failed early, but we try
            page.close()
        except Exception:
            pass
        try:
            if browser:
                browser.disconnect()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


def _extract_booking_detail(text):
    """Extract clean booking info lines from SriLankan result page."""
    lines = text.split('\n')
    details = []
    good_keywords = ['terminal', 'gate', 'boarding', 'departure', 'arrival',
                     'passenger', 'seat', 'baggage', 'colombo', 'class',
                     'economy', 'business', 'nonstop', 'duration', 'confirmed']
    junk_phrases = ['book', 'offer', 'download', 'newsletter', 'contact',
                    'login', 'sign up', 'cookie', 'privacy', 'terms',
                    'manage booking', 'loyalty', 'miles', 'facebook',
                    'twitter', 'instagram', 'copyright', 'follow us',
                    'prepaid', 'pre-order', 'celebrate', 'add cake',
                    'add meal', 'add extra', 'from usd']

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 3:
            continue
        line_lower = line_stripped.lower()
        if any(junk in line_lower for junk in junk_phrases):
            continue
        if any(kw in line_lower for kw in good_keywords):
            details.append(line_stripped)

    return ' | '.join(details[:6]) if details else 'Confirmed'


def _extract_flight_info(text, lastname):
    """Extract flight details from SriLankan result page."""
    segments = []

    # Flight numbers: UL followed by digits
    flight_matches = list(re.finditer(r'(UL\s*\d{1,4})', text))

    # 3-letter airport codes
    codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)
    if len(codes) < 2:
        codes = re.findall(r'\b([A-Z]{3})\b', text)
        non_airport = {'THE', 'AND', 'FOR', 'ARE', 'NOT', 'YOU', 'ALL', 'CAN',
                       'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET', 'HAS',
                       'HIM', 'HIS', 'HOW', 'MAN', 'NEW', 'NOW', 'OLD', 'SEE',
                       'WAY', 'WHO', 'BOY', 'DID', 'ITS', 'LET', 'PUT', 'SAY',
                       'SHE', 'TOO', 'USE', 'TAX', 'FEE', 'PRE', 'FAQ', 'APP',
                       'WEB', 'LOG', 'ADD', 'FLY', 'USD', 'EUR', 'GBP', 'LKR'}
        codes = [c for c in codes if c not in non_airport]

    # Times: HH:MM patterns
    times = re.findall(r'^\s*(\d{2}:\d{2})\s*$', text, re.MULTILINE)
    if not times:
        times = re.findall(r'\b(\d{2}:\d{2})\b', text)

    # Dates
    dates = re.findall(r'(?:\w+day,?\s+)?(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', text)
    parsed_dates = []
    for d in dates:
        try:
            date_str = f"{d[0]} {d[1]} {d[2]}"
            dt = datetime.strptime(date_str, '%d %B %Y')
            parsed_dates.append(dt.strftime('%Y-%m-%d'))
        except Exception:
            pass

    if not parsed_dates:
        dates_short = re.findall(r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),?\s*(\d{2,4})', text)
        for d in dates_short:
            try:
                day, mon, year = d[0], d[1], d[2]
                if len(year) == 2:
                    year = '20' + year
                dt = datetime.strptime(f'{day} {mon} {year}', '%d %b %Y')
                parsed_dates.append(dt.strftime('%Y-%m-%d'))
            except Exception:
                pass

    num_flights = len(flight_matches)
    if num_flights == 0:
        if (codes and len(codes) >= 2) or parsed_dates:
            info = {
                'flight_date': parsed_dates[0] if parsed_dates else '',
                'route': '',
                'flight_number': 'SriLankan Flight',
                'departure_time': times[0] if times else '',
                'arrival_time': times[1] if len(times) >= 2 else '',
                'passenger_name': lastname.capitalize(),
                'passenger_count': 1,
            }
            if len(codes) >= 2:
                for j in range(len(codes) - 1):
                    if codes[j] != codes[j+1]:
                        info['route'] = f"{codes[j]}-{codes[j+1]}"
                        break
                if not info['route']:
                    info['route'] = f"{codes[0]}-{codes[1]}"
            segments.append(info)
        return segments

    for i in range(num_flights):
        info = {
            'flight_date': parsed_dates[i] if i < len(parsed_dates) else '',
            'route': '',
            'flight_number': flight_matches[i].group(1).replace(' ', ''),
            'departure_time': times[i*2] if i*2 < len(times) else '',
            'arrival_time': times[i*2+1] if i*2+1 < len(times) else '',
            'passenger_name': lastname.capitalize(),
            'passenger_count': 1,
        }
        if i * 2 + 1 < len(codes):
            info['route'] = f"{codes[i*2]}-{codes[i*2+1]}"
        segments.append(info)

    return segments


def check_pnr_status(pnr, lastname, firstname=''):
    """
    Check SriLankan Airlines PNR status with retries.
    Uses a semaphore to prevent multiple concurrent CDP connections.
    """
    _cdp_semaphore.acquire()
    try:
        return _check_pnr_status_inner(pnr, lastname)
    finally:
        _cdp_semaphore.release()


def _check_pnr_status_inner(pnr, lastname):
    """Inner implementation with retry logic."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _try_check_pnr(pnr, lastname, attempt)
            if result.get('status') == 'Error':
                raise Exception(result['detail'])
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"SriLankan Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = attempt * 20 + random.randint(5, 15)
                logger.info(f"Waiting {wait_secs}s before retry...")
                time.sleep(wait_secs)

    logger.error(f"All {MAX_RETRIES} attempts failed for SriLankan PNR {pnr}: {last_error}")
    err_str = str(last_error).lower()
    if any(k in err_str for k in ['waf', 'incapsula', 'access denied', 'blocked']):
        return {
            'status': 'Check Failed',
            'detail': "SriLankan Airlines website is temporarily blocking automated checks. Will retry on next scheduled run.",
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
        pnr, lastname = sys.argv[1], sys.argv[2]
        print(f"Checking SriLankan Airlines PNR: {pnr} | {lastname}")
        result = check_pnr_status(pnr, lastname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
        if 'flight_info' in result:
            print(f"Flight Info: {result['flight_info']}")
    else:
        print("Usage: python scraper_srilankan.py <PNR> <LASTNAME>")
