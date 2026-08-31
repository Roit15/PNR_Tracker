"""
Thai Airways PNR Status Scraper.
Uses Selenium with stealth mode to check flight status on thaiairways.com

Key design:
  - Thai Airways My Trips page: https://www.thaiairways.com/en-lk/book/my-trips/
  - Form fields: "Booking Ref. / Ticket No." + "Last Name"
  - Submit button text: "Manage Booking"
  - Cookie consent via OneTrust (#onetrust-accept-btn-handler)
  - Flight numbers: TG XXX pattern
  - Uses the shared stealth driver from scraper.py
  - Retries up to 3 times on failure
"""

import os
import time
import logging
import re
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Import the stealth driver creator from the main scraper
from scraper import _create_stealth_driver

logger = logging.getLogger(__name__)

THAIAIRWAYS_URL = "https://www.thaiairways.com/en-lk/book/my-trips/"
MAX_RETRIES = 3


def _try_check_pnr(pnr, lastname, attempt=1):
    """Single attempt to check Thai Airways PNR. Returns result dict or raises."""
    driver = _create_stealth_driver()
    try:
        logger.info(f"[Thai Airways Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        driver.get(THAIAIRWAYS_URL)
        wait = WebDriverWait(driver, 40)

        # Wait for the React SPA to load
        time.sleep(10)

        # Dismiss cookie consent — Thai Airways uses OneTrust
        try:
            cookie_btn = driver.find_element(By.ID, 'onetrust-accept-btn-handler')
            if cookie_btn.is_displayed():
                cookie_btn.click()
                logger.info("Dismissed OneTrust cookie consent")
                time.sleep(1)
        except (NoSuchElementException, Exception):
            logger.debug("No cookie consent banner found")

        # Find form inputs — Thai Airways uses id="Booking Ref. / Ticket No." and id="Last Name"
        pnr_input = None
        lname_input = None

        # Strategy 1: Find by known IDs
        try:
            pnr_input = driver.find_element(By.ID, 'Booking Ref. / Ticket No.')
            logger.info("Found PNR input by ID")
        except NoSuchElementException:
            pass

        try:
            lname_input = driver.find_element(By.ID, 'Last Name')
            logger.info("Found Last Name input by ID")
        except NoSuchElementException:
            pass

        # Strategy 2: Find by placeholder
        if not pnr_input:
            try:
                pnr_input = driver.find_element(By.CSS_SELECTOR, 'input[placeholder*="Booking"]')
                logger.info("Found PNR input by placeholder")
            except NoSuchElementException:
                pass

        if not lname_input:
            try:
                lname_input = driver.find_element(By.CSS_SELECTOR, 'input[placeholder*="Last Name"]')
                logger.info("Found Last Name input by placeholder")
            except NoSuchElementException:
                pass

        # Strategy 3: Find by aria-label
        if not pnr_input:
            try:
                pnr_input = driver.find_element(By.CSS_SELECTOR, 'input[aria-label*="Booking"]')
                logger.info("Found PNR input by aria-label")
            except NoSuchElementException:
                pass

        if not lname_input:
            try:
                lname_input = driver.find_element(By.CSS_SELECTOR, 'input[aria-label*="Last Name"]')
                logger.info("Found Last Name input by aria-label")
            except NoSuchElementException:
                pass

        # Strategy 4: Fallback to first two visible text inputs
        if not pnr_input:
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
            visible_inputs = [i for i in inputs if i.is_displayed()]
            if len(visible_inputs) >= 2:
                pnr_input = visible_inputs[0]
                lname_input = visible_inputs[1]
                logger.info("Found inputs via fallback (first two visible)")
            elif len(visible_inputs) >= 1:
                pnr_input = visible_inputs[0]
                logger.info("Found PNR input via fallback (first visible)")

        if not pnr_input:
            raise Exception("Could not find booking reference input on Thai Airways page")

        # Fill booking reference
        pnr_input.clear()
        pnr_input.send_keys(pnr)
        time.sleep(0.5)

        # Fill last name
        if lname_input:
            lname_input.clear()
            lname_input.send_keys(lastname)
            time.sleep(0.5)

        # Find and click "Manage Booking" button
        submit_btn = None
        try:
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for btn in buttons:
                btn_text = (btn.text or '').strip().lower()
                if any(kw in btn_text for kw in ['manage booking', 'retrieve', 'search',
                                                   'find booking', 'submit', 'continue']):
                    if btn.is_displayed():
                        submit_btn = btn
                        logger.info(f"Found submit button: '{btn.text}'")
                        break
        except Exception:
            pass

        if not submit_btn:
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                logger.info("Found submit button by type=submit")
            except Exception:
                pass

        if submit_btn:
            driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", submit_btn)
            logger.info("Clicked submit button")
        else:
            # Try pressing Enter
            from selenium.webdriver.common.keys import Keys
            (lname_input or pnr_input).send_keys(Keys.RETURN)
            logger.info("Pressed Enter as fallback submit")

        # Wait for results — Thai Airways SPA loads booking details dynamically
        # The SPA navigates client-side, so we need to wait for the new route to render
        logger.info("Waiting for Thai Airways booking results to load...")
        time.sleep(8)  # Initial wait for SPA route change

        flight_data_keywords = ['booking confirmed', 'booking reference', 'trip itinerary',
                                'departure flight', 'return flight', 'economy', 'business',
                                'e-ticket', 'baggage allowance', 'terminal',
                                'not found', 'invalid booking', 'sorry', 'unable',
                                'cancelled', 'manage my booking']
        start_time = time.time()
        page_text = ""
        prev_len = 0
        stable_count = 0
        while time.time() - start_time < 45:
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text
                text_lower = page_text.lower()

                # Check for real content keywords
                has_flight_data = any(kw.lower() in text_lower for kw in flight_data_keywords)
                # Check for airport codes (e.g., BKK, HKG, MAA) with time nearby
                has_airport_codes = bool(re.findall(r'[A-Z]{3}\s+\d{2}:\d{2}', page_text))
                # Check for time patterns (e.g., 19:05)
                has_times = bool(re.findall(r'\d{2}:\d{2}', page_text))

                if (has_flight_data and len(page_text) > 800):
                    time.sleep(3)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                    logger.info(f"Got flight data after {time.time() - start_time:.0f}s ({len(page_text)} chars)")
                    break

                # Also check for error/not-found states
                if any(kw in text_lower for kw in ['not found', 'invalid', 'sorry', 'unable',
                                                     'error', 'no record', 'does not match']):
                    if len(page_text) > 200:
                        time.sleep(2)
                        page_text = driver.find_element(By.TAG_NAME, 'body').text
                        logger.info(f"Got error/not-found result after {time.time() - start_time:.0f}s")
                        break

                # Check if content has stabilized
                if len(page_text) == prev_len and len(page_text) > 800:
                    stable_count += 1
                    if stable_count >= 4:
                        logger.info(f"Page content stabilized after {time.time() - start_time:.0f}s ({len(page_text)} chars)")
                        break
                else:
                    stable_count = 0
                prev_len = len(page_text)

            except Exception:
                pass
            time.sleep(1)

        # Save screenshot
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        driver.save_screenshot(os.path.join(screenshots_dir, f'TG_{pnr}_status.png'))

        # Save raw text for debugging
        raw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'TG_{pnr}_raw.txt')
        with open(raw_path, 'w') as f:
            f.write(page_text)

        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}
        text_lower = page_text.lower()

        # Status detection
        if any(kw in text_lower for kw in ['not found', 'invalid', 'does not match',
                                            'cannot be found', 'no booking', 'unable to retrieve',
                                            'sorry', 'no record', 'no result']):
            result['status'] = 'Not Found'
            result['detail'] = 'PNR not found or invalid on Thai Airways.'

        elif 'cancelled' in text_lower:
            result['status'] = 'Cancelled'
            result['detail'] = 'Booking appears to be cancelled.'

        elif any(kw in text_lower for kw in ['booking confirmed', 'trip itinerary',
                                              'manage my booking', 'your booking',
                                              'booking details', 'booking reference',
                                              'passenger']):
            result['status'] = 'Confirmed'
            result['detail'] = _extract_booking_detail(page_text)

        elif any(kw in text_lower for kw in ['completed', 'flown', 'past trip']):
            result['status'] = 'Completed'
            result['detail'] = 'Flight has been completed.'

        elif 'check-in' in text_lower or 'checkin' in text_lower:
            result['status'] = 'Check-in Open'
            result['detail'] = _extract_booking_detail(page_text)

        else:
            result['status'] = 'Checked'
            result['detail'] = page_text[:500] if page_text else 'Could not parse status'

        if result['status'] not in ('Error', 'Not Found'):
            result['flight_info'] = _extract_flight_info(page_text, lastname)

        return result

    finally:
        try:
            driver.get("about:blank")
        except Exception:
            pass


def _extract_booking_detail(text):
    """Extract clean booking info lines from Thai Airways result page."""
    lines = text.split('\n')
    details = []
    good_keywords = ['terminal', 'gate', 'boarding', 'departure', 'arrival',
                     'passenger', 'seat', 'baggage', 'economy', 'business',
                     'e-ticket', 'class', 'bangkok', 'carbon']
    junk_phrases = ['book', 'offer', 'download', 'newsletter', 'contact',
                    'login', 'sign up', 'cookie', 'privacy', 'terms',
                    'subscribe', 'connect with', 'loyalty', 'facebook',
                    'twitter', 'instagram', 'help center', 'refund',
                    'bellugg', 'hertz', 'avis', 'sixt']

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 3:
            continue
        line_lower = line_stripped.lower()
        if any(junk in line_lower for junk in junk_phrases):
            continue
        if any(kw in line_lower for kw in good_keywords):
            details.append(line_stripped)

    return ' | '.join(details[:8]) if details else 'Confirmed'


def _extract_flight_info(text, lastname):
    """Extract flight details from Thai Airways result page."""
    segments = []

    # Flight numbers: TG followed by digits (e.g., TG 639, TG 337)
    flight_matches = list(re.finditer(r'(TG\s*\d{1,4})', text))

    # 3-letter airport codes on their own lines
    codes = re.findall(r'^([A-Z]{3})\b', text, re.MULTILINE)
    # Also try inline codes with time patterns like "HKG 19:05"
    inline_codes = re.findall(r'\b([A-Z]{3})\s+\d{2}:\d{2}', text)
    if inline_codes:
        codes = inline_codes + codes

    if len(codes) < 2:
        codes = re.findall(r'\b([A-Z]{3})\b', text)
        # Filter to likely airport codes
        non_airport = {'THE', 'AND', 'FOR', 'ARE', 'NOT', 'YOU', 'ALL', 'CAN',
                       'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET', 'HAS',
                       'HIM', 'HIS', 'HOW', 'MAN', 'NEW', 'NOW', 'OLD', 'SEE',
                       'WAY', 'WHO', 'BOY', 'DID', 'ITS', 'LET', 'PUT', 'SAY',
                       'SHE', 'TOO', 'USE', 'TAX', 'FEE', 'PRE', 'FAQ', 'APP',
                       'WEB', 'LOG', 'ADD', 'FLY', 'KGS', 'NOT', 'SIT', 'VIA',
                       'PLZ', 'BKK'}  # BKK is valid airport but exclude from generic filter
        codes = [c for c in codes if c not in non_airport]

    # Times: prioritize flight times next to airport codes to avoid booking timestamps
    flight_times = re.findall(r'[A-Z]{3}\s+(\d{2}:\d{2})|(\d{2}:\d{2})\s+[A-Z]{3}', text)
    flight_times = [t[0] or t[1] for t in flight_times]
    times = flight_times if flight_times else re.findall(r'\b(\d{2}:\d{2})\b', text)

    # Dates: "Thu, 22 Oct 2026" or "22 Oct 2026" or "22 Oct, 2026"
    dates = re.findall(r'(?:[A-Z][a-z]{2},?\s+)?(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})', text)
    if not dates:
        dates = re.findall(r'(\d{1,2}\s+[A-Z][a-z]{2},?\s*\d{2,4})', text)

    # Passenger name
    passenger_name = ''
    name_match = re.search(r'(?:MR|MS|MRS|DR)\s+([A-Z\s]+?' + re.escape(lastname.upper()) + r')\b', text)
    if name_match:
        passenger_name = name_match.group(1).strip()
    else:
        # Try finding lastname in passenger section
        for line in text.split('\n'):
            if lastname.upper() in line.upper() and any(t in line.upper() for t in ['MR', 'MS', 'MRS']):
                passenger_name = line.strip()
                break

    # Passenger count
    pax_match = re.search(r'(\d+)\s*Adult', text, re.IGNORECASE)
    pax_count = int(pax_match.group(1)) if pax_match else 1

    # E-ticket number
    eticket = ''
    et_match = re.search(r'(?:E-Ticket|Ticket)\s*(?:Number|No\.?)?\s*[:\-]?\s*(\d{13})', text)
    if et_match:
        eticket = et_match.group(1)

    # Build segments from flight numbers
    # Thai Airways format: "HKG 19:05 ... MAA 23:45" with "TG 639\nTG 337"
    num_flights = len(flight_matches)

    if num_flights == 0:
        # Build a single segment from available data
        if (codes and len(codes) >= 2) or dates:
            info = {
                'flight_date': '',
                'route': '',
                'flight_number': 'Thai Airways Flight',
                'departure_time': '',
                'arrival_time': '',
                'passenger_name': passenger_name or lastname.capitalize(),
                'passenger_count': pax_count,
            }
            if len(codes) >= 2:
                for j in range(len(codes) - 1):
                    if codes[j] != codes[j+1]:
                        info['route'] = f"{codes[j]}-{codes[j+1]}"
                        break
                if not info['route']:
                    info['route'] = f"{codes[0]}-{codes[1]}"
            if times:
                info['departure_time'] = times[0]
                if len(times) >= 2:
                    info['arrival_time'] = times[1]
            if dates:
                try:
                    date_str = dates[0].replace(',', '')
                    parts = date_str.split()
                    if len(parts[-1]) == 2:
                        parts[-1] = "20" + parts[-1]
                    date_str = " ".join(parts)
                    dt = datetime.strptime(date_str, '%d %b %Y')
                    info['flight_date'] = dt.strftime('%Y-%m-%d')
                except Exception:
                    info['flight_date'] = dates[0]
            segments.append(info)
        return segments

    # For the overall route, find origin and destination from page text
    # Thai Airways shows "Hong Kong → Chennai" or "HKG 19:05 ... MAA 23:45"
    origin_dest_codes = re.findall(r'([A-Z]{3})\s+\d{2}:\d{2}', text)

    for i in range(num_flights):
        info = {
            'flight_date': '',
            'route': '',
            'flight_number': flight_matches[i].group(1).replace(' ', ' ').strip(),
            'departure_time': '',
            'arrival_time': '',
            'passenger_name': passenger_name or lastname.capitalize(),
            'passenger_count': pax_count,
        }

        # Route from origin-dest codes
        if len(origin_dest_codes) >= 2:
            info['route'] = f"{origin_dest_codes[0]}-{origin_dest_codes[-1]}"

        # Times
        if i * 2 + 1 < len(times):
            info['departure_time'] = times[i * 2]
            info['arrival_time'] = times[i * 2 + 1]
        elif i == 0 and times:
            info['departure_time'] = times[0]
            if len(times) >= 2:
                info['arrival_time'] = times[1]

        # Dates
        if i < len(dates):
            try:
                date_str = dates[i].replace(',', '')
                parts = date_str.split()
                if len(parts[-1]) == 2:
                    parts[-1] = "20" + parts[-1]
                date_str = " ".join(parts)
                dt = datetime.strptime(date_str, '%d %b %Y')
                info['flight_date'] = dt.strftime('%Y-%m-%d')
            except Exception:
                pass
        elif dates:
            # Use first date for all segments if only one date found
            try:
                date_str = dates[0].replace(',', '')
                parts = date_str.split()
                if len(parts[-1]) == 2:
                    parts[-1] = "20" + parts[-1]
                date_str = " ".join(parts)
                dt = datetime.strptime(date_str, '%d %b %Y')
                info['flight_date'] = dt.strftime('%Y-%m-%d')
            except Exception:
                pass

        segments.append(info)

    return segments


def check_pnr_status(pnr, lastname, firstname=''):
    """
    Check Thai Airways PNR status with retries.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _try_check_pnr(pnr, lastname, attempt)
            if result.get('status') == 'Error':
                raise Exception(result['detail'])
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"Thai Airways Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = attempt * 15
                logger.info(f"Waiting {wait_secs}s before retry...")
                time.sleep(wait_secs)

    logger.error(f"All {MAX_RETRIES} attempts failed for Thai Airways PNR {pnr}: {last_error}")
    err_str = str(last_error).lower()
    if any(k in err_str for k in ["waf", "cloudfront", "blocked", "access denied", "403"]):
        return {
            "status": "Check Failed",
            "detail": "Website is temporarily blocking automated checks (WAF). Will retry on next scheduled run.",
            "raw_text": "",
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
        print(f"Checking Thai Airways PNR: {pnr} | {lastname}")
        result = check_pnr_status(pnr, lastname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
        if 'flight_info' in result:
            print(f"Flight Info: {result['flight_info']}")
    else:
        print("Usage: python scraper_thaiairways.py <PNR> <LASTNAME>")
