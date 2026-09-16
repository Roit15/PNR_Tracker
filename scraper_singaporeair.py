"""
Singapore Airlines PNR Status Scraper.
Uses Selenium with stealth mode to check flight status.
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

SA_URL = "https://www.singaporeair.com/en_UK/sg/plan-travel/your-booking/managebooking/"
MAX_RETRIES = 3


def _try_check_pnr(pnr, lastname, attempt=1):
    """Single attempt to check Singapore Airlines PNR. Returns result dict or raises."""
    driver = None
    try:
        logger.info(f"[SA Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        from scraper import _is_cloud
        if _is_cloud():
            logger.warning("Singapore Airlines scraping is disabled on Cloud/VPS due to reCAPTCHA IP blocks.")
            return {'status': 'Pending Check', 'detail': 'Will be checked by local sync engine.', 'raw_text': ''}

        driver = _create_stealth_driver()
        driver.get(SA_URL)
        wait = WebDriverWait(driver, 30)
        
        # Accept cookies if the button is there
        try:
            accept_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]")))
            accept_btn.click()
            time.sleep(1)
        except Exception:
            pass

        # Last Name has id lasFamilyNameInputField, PNR is the text input immediately preceding it
        try:
            lname_input = driver.find_element(By.ID, "lasFamilyNameInputField")
            pnr_input = driver.find_element(By.XPATH, '//input[@id="lasFamilyNameInputField"]/preceding::input[@type="text"][1]')
        except Exception:
            raise Exception("Could not find PNR and Last Name input fields")
        
        pnr_input.clear()
        pnr_input.send_keys(pnr)
        time.sleep(0.5)
        
        lname_input.clear()
        lname_input.send_keys(lastname)
        time.sleep(0.5)
        
        # Click the manage booking submit button
        submit_btn = driver.find_element(By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'manage booking')]")
        driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
        time.sleep(0.5)
        submit_btn.click()
        
        # Wait for results
        result_keywords = ['flight', 'confirmed', 'cancelled', 'not found', 'invalid', 'error', 'departure']
        start_time = time.time()
        page_text = ""
        while time.time() - start_time < 40:
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text
                text_lower = page_text.lower()
                if any(kw in text_lower for kw in result_keywords) and len(page_text) > 200:
                    time.sleep(2)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                    break
            except Exception:
                pass
            time.sleep(0.5)

        # Save screenshot
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        driver.save_screenshot(os.path.join(screenshots_dir, f'SA_{pnr}_status.png'))
        
        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}
        text_lower = page_text.lower()

        # Status detection
        if 'not found' in text_lower or 'invalid' in text_lower or 'does not match' in text_lower or 'cannot be found' in text_lower:
            result['status'] = 'Not Found'
            result['detail'] = 'PNR not found or invalid on Singapore Airlines.'
        elif 'error code' in text_lower and 'something went wrong' in text_lower:
            result['status'] = 'Error'
            result['detail'] = 'Singapore Airlines website blocked the request or encountered an error.'
        elif 'cancelled' in text_lower:
            result['status'] = 'Cancelled'
            result['detail'] = 'Booking appears to be cancelled.'
        elif 'confirmed' in text_lower or 'manage your' in text_lower or 'your flights' in text_lower:
            result['status'] = 'Confirmed'
            result['detail'] = _extract_booking_detail(page_text)
        elif 'completed' in text_lower or 'flown' in text_lower:
            result['status'] = 'Completed'
            result['detail'] = 'Flight has been completed.'
        else:
            result['status'] = 'Checked'
            result['detail'] = page_text[:500] if page_text else 'Could not parse status'

        if result['status'] not in ('Error', 'Not Found', 'Cancelled'):
            result['flight_info'] = _extract_flight_info(page_text, lastname)

        return result

    finally:
        from scraper import _kill_driver
        _kill_driver(driver)

def _extract_booking_detail(text):
    """Extract clean booking info lines."""
    lines = text.split('\n')
    details = []
    # Try to grab lines near 'Confirmed'
    for i, line in enumerate(lines):
        if 'confirmed' in line.lower():
            start = max(0, i - 2)
            end = min(len(lines), i + 4)
            for j in range(start, end):
                if lines[j].strip() and lines[j].strip().lower() != 'confirmed':
                    details.append(lines[j].strip())
    
    # deduplicate but keep order
    seen = set()
    dedup = []
    for d in details:
        if d not in seen:
            seen.add(d)
            dedup.append(d)
            
    return ' | '.join(dedup[:6]) if dedup else 'Confirmed'

def _extract_flight_info(text, lastname):
    """Extract flight details from SA result page."""
    # This might return multiple segments if there are connecting flights
    # Example text:
    # Delhi to Singapore  •  SQ 401
    # Confirmed
    # DEL
    #  09:00
    # Thu 06 Aug 2026
    # Indira Gandhi Intl Terminal 3
    # 5h 45m
    # SIN
    #  17:15
    # Thu 06 Aug 2026
    
    segments = []
    
    # Try to extract dates and flights by regex
    # SQ followed by digits
    flight_matches = list(re.finditer(r'(SQ\s*\d{3,4})', text))
    
    # 3-letter codes
    codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)
    
    # times
    times = re.findall(r'^\s*(\d{2}:\d{2})\s*$', text, re.MULTILINE)
    
    # dates (e.g. Thu 06 Aug 2026)
    dates = re.findall(r'^[A-Z][a-z]{2}\s(\d{2}\s[A-Z][a-z]{2}\s\d{4})$', text, re.MULTILINE)
    
    num_flights = len(flight_matches)
    if num_flights == 0:
        return []
        
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
        if i * 2 < len(dates):
            try:
                dt = datetime.strptime(dates[i*2], '%d %b %Y')
                info['flight_date'] = dt.strftime('%Y-%m-%d')
            except:
                pass
                
        segments.append(info)
        
    return segments

def check_pnr_status(pnr, lastname, firstname=''):
    """
    Check SA PNR status with retries.
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
            logger.warning(f"SA Attempt {attempt}/{MAX_RETRIES} failed for PNR {pnr}: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = attempt * 15
                logger.info(f"Waiting {wait_secs}s before retry...")
                time.sleep(wait_secs)

    logger.error(f"All {MAX_RETRIES} attempts failed for SA PNR {pnr}: {last_error}")
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
        print(f"Checking SA PNR: {pnr} | {lastname}")
        result = check_pnr_status(pnr, lastname)
        print(f"\nStatus: {result['status']}")
        print(f"Detail: {result['detail']}")
        if 'flight_info' in result:
            print(f"Flight Info: {result['flight_info']}")
    else:
        print("Usage: python scraper_singaporeair.py <PNR> <LASTNAME>")
