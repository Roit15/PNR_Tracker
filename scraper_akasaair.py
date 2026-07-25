"""
Akasa Air PNR Status Scraper.
Uses Selenium with stealth mode to check flight status on akasaair.com

Key design:
  - Akasa Air is a Next.js SPA — the PNR widget loads client-side
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

AKASA_URL = "https://www.akasaair.com/manage-booking"
MAX_RETRIES = 3


def _try_check_pnr(pnr, lastname, attempt=1):
    """Single attempt to check Akasa Air PNR. Returns result dict or raises."""
    driver = _create_stealth_driver()
    try:
        logger.info(f"[Akasa Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        driver.get(AKASA_URL)
        wait = WebDriverWait(driver, 40)

        # Wait for the page to fully load (Next.js SPA)
        time.sleep(10)

        # Dismiss cookie consent if present
        try:
            cookie_btns = driver.find_elements(By.XPATH,
                "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]")
            for btn in cookie_btns:
                try:
                    btn.click()
                    time.sleep(1)
                    break
                except Exception:
                    pass
        except Exception:
            pass

        # Try multiple strategies to find the PNR input field
        pnr_input = None
        lname_input = None

        # Strategy 1: Look for input with placeholder containing PNR/booking
        try:
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
            for inp in inputs:
                placeholder = (inp.get_attribute('placeholder') or '').lower()
                aria_label = (inp.get_attribute('aria-label') or '').lower()
                name_attr = (inp.get_attribute('name') or '').lower()
                if any(kw in placeholder or kw in aria_label or kw in name_attr
                       for kw in ['pnr', 'booking', 'reference', 'confirmation']):
                    pnr_input = inp
                elif any(kw in placeholder or kw in aria_label or kw in name_attr
                         for kw in ['last name', 'surname', 'family name', 'lastname']):
                    lname_input = inp
        except Exception:
            pass

        # Strategy 2: If not found, just take the first two text inputs
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

        if not pnr_input:
            # Try waiting a bit more for the SPA widget to render
            time.sleep(10)
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
            visible_inputs = [i for i in inputs if i.is_displayed()]
            if len(visible_inputs) >= 2:
                pnr_input = visible_inputs[0]
                lname_input = visible_inputs[1]
            elif len(visible_inputs) >= 1:
                pnr_input = visible_inputs[0]

        if not pnr_input:
            raise Exception("Could not find PNR input field on Akasa Air page")

        # Fill PNR
        pnr_input.clear()
        pnr_input.send_keys(pnr)
        time.sleep(0.5)

        # Fill Last Name
        if lname_input:
            lname_input.clear()
            lname_input.send_keys(lastname)
            time.sleep(0.5)

        # Find and click the submit button
        submit_btn = None
        try:
            # Look for button with relevant text
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for btn in buttons:
                btn_text = (btn.text or '').lower()
                if any(kw in btn_text for kw in ['retrieve', 'search', 'view booking', 'submit', 'find', 'manage', 'get details']):
                    if btn.is_displayed():
                        submit_btn = btn
                        break
        except Exception:
            pass

        if not submit_btn:
            # Try any primary/submit button near the inputs
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            except Exception:
                pass

        if submit_btn:
            driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
            time.sleep(0.5)
            submit_btn.click()
        else:
            # Try pressing Enter on the last input
            from selenium.webdriver.common.keys import Keys
            (lname_input or pnr_input).send_keys(Keys.RETURN)

        # Wait for results to load
        result_keywords = ['flight', 'confirmed', 'cancelled', 'not found', 'invalid',
                          'error', 'departure', 'itinerary', 'passenger', 'booking details',
                          'no booking', 'sorry']
        start_time = time.time()
        page_text = ""
        while time.time() - start_time < 40:
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text
                text_lower = page_text.lower()
                if any(kw in text_lower for kw in result_keywords) and len(page_text) > 300:
                    time.sleep(3)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                    break
            except Exception:
                pass
            time.sleep(1)

        # Save screenshot
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        driver.save_screenshot(os.path.join(screenshots_dir, f'QP_{pnr}_status.png'))

        # Save raw text for debugging
        raw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'QP_{pnr}_raw.txt')
        with open(raw_path, 'w') as f:
            f.write(page_text)

        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}
        text_lower = page_text.lower()

        # Status detection
        if any(kw in text_lower for kw in ['not found', 'invalid', 'no booking', 'does not exist',
                                            'no record', 'unable to find', 'sorry']):
            result['status'] = 'Not Found'
            result['detail'] = 'PNR not found or invalid on Akasa Air.'
        elif 'cancelled' in text_lower:
            result['status'] = 'Cancelled'
            result['detail'] = 'Booking appears to be cancelled.'
        elif any(kw in text_lower for kw in ['confirmed', 'booked', 'itinerary', 'booking details',
                                              'passenger', 'departure', 'arrival']):
            result['status'] = 'Confirmed'
            result['detail'] = _extract_booking_detail(page_text)
        elif any(kw in text_lower for kw in ['completed', 'flown', 'past']):
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
    """Extract clean booking info lines from Akasa Air result page."""
    lines = text.split('\n')
    details = []
    good_keywords = ['terminal', 'gate', 'boarding', 'departure', 'arrival',
                     'passenger', 'seat', 'baggage']
    junk_phrases = ['book', 'offer', 'download', 'newsletter', 'contact',
                    'login', 'sign up', 'cookie', 'privacy', 'terms',
                    'manage booking', 'add-on', 'cafe akasa']

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
    """Extract flight details from Akasa Air result page."""
    segments = []

    # Flight numbers: QP followed by digits
    flight_matches = list(re.finditer(r'(QP\s*\d{3,4})', text))

    # 3-letter airport codes on their own lines
    codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)

    # Times: HH:MM patterns
    times = re.findall(r'^\s*(\d{2}:\d{2})\s*$', text, re.MULTILINE)

    # Dates: various formats
    # "25 Jul 2026" or "25 Jul, 2026" or "Fri 25 Jul 2026"
    dates = re.findall(r'(?:[A-Z][a-z]{2}\s)?(\d{1,2}\s[A-Z][a-z]{2}\s\d{4})', text)

    # Also try "25 Jul, 26" short format
    if not dates:
        dates_short = re.findall(r'(\d{1,2}\s[A-Z][a-z]{2},?\s*\d{2,4})', text)
        dates = dates_short

    num_flights = len(flight_matches)
    if num_flights == 0:
        # Try to build a single segment from available data
        if codes and dates:
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
    Check Akasa Air PNR status with retries.
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
            logger.warning(f"Akasa Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = attempt * 15
                logger.info(f"Waiting {wait_secs}s before retry...")
                time.sleep(wait_secs)

    logger.error(f"All {MAX_RETRIES} attempts failed for Akasa PNR {pnr}: {last_error}")
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
        print(f"Checking Akasa Air PNR: {pnr} | {lastname}")
        result = check_pnr_status(pnr, lastname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
        if 'flight_info' in result:
            print(f"Flight Info: {result['flight_info']}")
    else:
        print("Usage: python scraper_akasaair.py <PNR> <LASTNAME>")
