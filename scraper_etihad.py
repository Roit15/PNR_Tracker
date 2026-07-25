"""
Etihad Airways PNR Status Scraper.
Uses Selenium with stealth mode to check flight status on etihad.com

Key design:
  - Etihad's manage booking page requires booking reference + last name
  - Uses the shared stealth driver from scraper.py
  - Retries up to 3 times on failure with increasing wait
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

ETIHAD_URL = "https://www.etihad.com/en/manage"
MAX_RETRIES = 3


def _try_check_pnr(pnr, lastname, attempt=1):
    """Single attempt to check Etihad PNR. Returns result dict or raises."""
    driver = _create_stealth_driver()
    try:
        logger.info(f"[Etihad Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        driver.get(ETIHAD_URL)
        wait = WebDriverWait(driver, 40)

        # Wait for the page to load
        time.sleep(8)

        # Dismiss cookie consent — Etihad uses a "Close" button on their cookie banner
        try:
            cookie_selectors = [
                "//button[normalize-space(text())='Close']",
                "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'close')]",
                "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
                "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
                "//button[contains(@class, 'cookie')]",
                "//button[@id='onetrust-accept-btn-handler']",
            ]
            for selector in cookie_selectors:
                try:
                    btns = driver.find_elements(By.XPATH, selector)
                    for btn in btns:
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].click();", btn)
                            logger.info(f"Clicked cookie button: {selector}")
                            time.sleep(1)
                            break
                except Exception:
                    continue
        except Exception:
            pass

        # Find form inputs — try multiple strategies
        pnr_input = None
        lname_input = None

        # Strategy 1: Look for inputs by placeholder/label/aria-label
        try:
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
            for inp in inputs:
                if not inp.is_displayed():
                    continue
                placeholder = (inp.get_attribute('placeholder') or '').lower()
                aria_label = (inp.get_attribute('aria-label') or '').lower()
                name_attr = (inp.get_attribute('name') or '').lower()
                id_attr = (inp.get_attribute('id') or '').lower()
                all_attrs = f"{placeholder} {aria_label} {name_attr} {id_attr}"

                if any(kw in all_attrs for kw in ['booking', 'pnr', 'reference', 'confirmation', 'record']):
                    pnr_input = inp
                elif any(kw in all_attrs for kw in ['last name', 'surname', 'family', 'lastname']):
                    lname_input = inp
        except Exception:
            pass

        # Strategy 2: If not found by attribute, take first two visible text inputs
        if not pnr_input:
            try:
                inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
                visible_inputs = [i for i in inputs if i.is_displayed()]
                if len(visible_inputs) >= 2:
                    pnr_input = visible_inputs[0]
                    lname_input = visible_inputs[1]
                elif len(visible_inputs) == 1:
                    pnr_input = visible_inputs[0]
            except Exception:
                pass

        # Strategy 3: Wait more and retry
        if not pnr_input:
            time.sleep(10)
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
            visible_inputs = [i for i in inputs if i.is_displayed()]
            if len(visible_inputs) >= 2:
                pnr_input = visible_inputs[0]
                lname_input = visible_inputs[1]
            elif len(visible_inputs) >= 1:
                pnr_input = visible_inputs[0]

        if not pnr_input:
            raise Exception("Could not find booking reference input on Etihad page")

        # Fill booking reference
        pnr_input.clear()
        pnr_input.send_keys(pnr)
        time.sleep(0.5)

        # Fill last name
        if lname_input:
            lname_input.clear()
            lname_input.send_keys(lastname)
            time.sleep(0.5)

        # Find and click submit button
        submit_btn = None
        try:
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for btn in buttons:
                btn_text = (btn.text or '').lower()
                if any(kw in btn_text for kw in ['retrieve', 'search', 'find', 'submit',
                                                   'manage', 'view', 'continue', 'get']):
                    if btn.is_displayed():
                        submit_btn = btn
                        break
        except Exception:
            pass

        if not submit_btn:
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            except Exception:
                pass

        if submit_btn:
            driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", submit_btn)
        else:
            # Try pressing Enter
            from selenium.webdriver.common.keys import Keys
            (lname_input or pnr_input).send_keys(Keys.RETURN)

        # Wait for results — Etihad is a heavy SPA, skeleton loads first then real content
        # We need to wait for ACTUAL flight data (airport codes, times, dates) not just nav text
        logger.info("Waiting for Etihad booking results to load...")
        flight_data_keywords = ['departure', 'arrival', 'terminal', 'economy', 'business',
                                'guest', 'abu dhabi', 'passenger', 'seat', 'baggage',
                                'not found', 'invalid', 'sorry', 'unable', 'error',
                                'cancelled', 'EY']
        start_time = time.time()
        page_text = ""
        prev_len = 0
        stable_count = 0
        while time.time() - start_time < 60:
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text
                text_lower = page_text.lower()

                # Check if actual flight data keywords are present
                has_flight_data = any(kw.lower() in text_lower for kw in flight_data_keywords)
                # Check for 3-letter airport codes (e.g., DEL, AUH, BOM)
                has_airport_codes = bool(re.findall(r'\b[A-Z]{3}\b', page_text))
                # Check for time patterns (e.g., 14:30)
                has_times = bool(re.findall(r'\d{2}:\d{2}', page_text))

                if (has_flight_data and (has_airport_codes or has_times) and
                        len(page_text) > 500):
                    # Content looks real — wait a bit more to ensure it's stable
                    time.sleep(3)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                    logger.info(f"Got flight data after {time.time() - start_time:.0f}s ({len(page_text)} chars)")
                    break

                # Also check if content has stabilized (SPA finished rendering)
                if len(page_text) == prev_len and len(page_text) > 500:
                    stable_count += 1
                    if stable_count >= 4:  # Stable for 4 seconds
                        logger.info(f"Page content stabilized after {time.time() - start_time:.0f}s")
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
        driver.save_screenshot(os.path.join(screenshots_dir, f'EY_{pnr}_status.png'))

        # Save raw text for debugging
        raw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'EY_{pnr}_raw.txt')
        with open(raw_path, 'w') as f:
            f.write(page_text)

        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}
        text_lower = page_text.lower()

        # Status detection
        if any(kw in text_lower for kw in ['not found', 'invalid', 'does not match',
                                            'cannot be found', 'no booking', 'unable to retrieve',
                                            'sorry', 'no record']):
            result['status'] = 'Not Found'
            result['detail'] = 'PNR not found or invalid on Etihad Airways.'
        elif 'cancelled' in text_lower:
            result['status'] = 'Cancelled'
            result['detail'] = 'Booking appears to be cancelled.'
        elif any(kw in text_lower for kw in ['confirmed', 'your trip', 'your journey',
                                              'manage your', 'your flights', 'itinerary',
                                              'booking details', 'passenger']):
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
        driver.quit()


def _extract_booking_detail(text):
    """Extract clean booking info lines from Etihad result page."""
    lines = text.split('\n')
    details = []
    good_keywords = ['terminal', 'gate', 'boarding', 'departure', 'arrival',
                     'passenger', 'seat', 'baggage', 'abu dhabi', 'class']
    junk_phrases = ['book', 'offer', 'download', 'newsletter', 'contact',
                    'login', 'sign up', 'cookie', 'privacy', 'terms',
                    'manage booking', 'loyalty', 'miles', 'facebook',
                    'twitter', 'instagram']

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
    """Extract flight details from Etihad result page."""
    segments = []

    # Flight numbers: EY followed by digits
    flight_matches = list(re.finditer(r'(EY\s*\d{1,4})', text))

    # 3-letter airport codes on their own lines
    codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)
    # Also try inline codes
    if len(codes) < 2:
        codes = re.findall(r'\b([A-Z]{3})\b', text)
        # Filter to likely airport codes (exclude common English 3-letter words)
        non_airport = {'THE', 'AND', 'FOR', 'ARE', 'NOT', 'YOU', 'ALL', 'CAN',
                       'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET', 'HAS',
                       'HIM', 'HIS', 'HOW', 'MAN', 'NEW', 'NOW', 'OLD', 'SEE',
                       'WAY', 'WHO', 'BOY', 'DID', 'ITS', 'LET', 'PUT', 'SAY',
                       'SHE', 'TOO', 'USE', 'TAX', 'FEE', 'PRE', 'FAQ', 'APP',
                       'WEB', 'LOG', 'ADD', 'FLY'}
        codes = [c for c in codes if c not in non_airport]

    # Times: HH:MM patterns
    times = re.findall(r'^\s*(\d{2}:\d{2})\s*$', text, re.MULTILINE)
    if not times:
        times = re.findall(r'\b(\d{2}:\d{2})\b', text)

    # Dates: "25 Jul 2026" or "Fri 25 Jul 2026" or "25 Jul"
    dates = re.findall(r'(?:[A-Z][a-z]{2}\s)?(\d{1,2}\s[A-Z][a-z]{2}\s\d{4})', text)
    if not dates:
        dates = re.findall(r'(\d{1,2}\s[A-Z][a-z]{2},?\s*\d{2,4})', text)

    num_flights = len(flight_matches)
    if num_flights == 0:
        # Try to build a single segment from available data
        if (codes and len(codes) >= 2) or dates:
            info = {
                'flight_date': '',
                'route': '',
                'flight_number': '',
                'departure_time': '',
                'arrival_time': '',
                'passenger_name': lastname.capitalize(),
                'passenger_count': 1,
            }
            if len(codes) >= 2:
                # Find first pair of distinct codes
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
                    pass
            segments.append(info)
        return segments

    for i in range(num_flights):
        info = {
            'flight_date': '',
            'route': '',
            'flight_number': flight_matches[i].group(1).replace(' ', ''),
            'departure_time': '',
            'arrival_time': '',
            'passenger_name': lastname.capitalize(),
            'passenger_count': 1,
        }

        # Route
        if i * 2 + 1 < len(codes):
            info['route'] = f"{codes[i*2]}-{codes[i*2+1]}"

        # Times
        if i * 2 + 1 < len(times):
            info['departure_time'] = times[i*2]
            info['arrival_time'] = times[i*2+1]

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

        segments.append(info)

    return segments


def check_pnr_status(pnr, lastname, firstname=''):
    """
    Check Etihad PNR status with retries.
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
            logger.warning(f"Etihad Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = attempt * 15
                logger.info(f"Waiting {wait_secs}s before retry...")
                time.sleep(wait_secs)

    logger.error(f"All {MAX_RETRIES} attempts failed for Etihad PNR {pnr}: {last_error}")
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
        print(f"Checking Etihad PNR: {pnr} | {lastname}")
        result = check_pnr_status(pnr, lastname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
        if 'flight_info' in result:
            print(f"Flight Info: {result['flight_info']}")
    else:
        print("Usage: python scraper_etihad.py <PNR> <LASTNAME>")
