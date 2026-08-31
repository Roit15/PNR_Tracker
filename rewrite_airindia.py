import re

with open('scraper_airindia_old.py', 'r') as f:
    content = f.read()

# The extraction functions start at `def extract_flight_info_from_web`
extraction_code_idx = content.find("def extract_flight_info_from_web")
extraction_code = content[extraction_code_idx:]

new_header_and_logic = """\"\"\"
Air India PNR Status Scraper.
Uses Playwright with CDP to check flight status on airindia.com
\"\"\"

import os
import time
import logging
import re
import random
from datetime import datetime

logger = logging.getLogger(__name__)

AIRINDIA_URL = "https://www.airindia.com/in/en/manage/booking.html"
MAX_RETRIES = 1

def _human_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))

def _try_check_pnr(pnr, lastname, attempt=1):
    from playwright.sync_api import sync_playwright
    import chrome_launcher

    logger.info(f"[AI Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

    chrome_launcher.ensure_chrome_running()
    pw = sync_playwright().start()
    browser = None
    context = None
    page = None
    try:
        try:
            browser = pw.chromium.connect_over_cdp("http://localhost:9224")
        except Exception as e:
            pw.stop()
            raise Exception("Could not connect to Chrome on port 9224.") from e

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        logger.info("Navigating to manage booking page...")
        page.goto(AIRINDIA_URL, wait_until='domcontentloaded', timeout=60000)
        _human_delay(5.0, 9.0)

        # Check if page got blocked
        page_text = page.inner_text('body').lower()
        if 'incapsula incident' in page_text or 'request unsuccessful' in page_text or 'access denied' in page_text:
            raise Exception("Imperva WAF blocked the page load — will retry with fresh browser")

        # Fill out the form
        try:
            page.fill("input[name='pnr-ip']", pnr, timeout=10000)
            page.fill("input[name='lastname-ip']", lastname, timeout=10000)
        except Exception:
            # Fallback to old names if they randomly revert
            try:
                page.fill("input[name='pnr']", pnr, timeout=5000)
                page.fill("input[name='lastName']", lastname, timeout=5000)
            except Exception:
                raise Exception("Could not find PNR/Last Name inputs.")
                
        _human_delay(0.5, 1.5)
        
        try:
            page.click("button.bi-submit-btn, button[type='submit']", timeout=10000)
        except Exception:
            raise Exception("Could not find submit button")

        # Save pre-result screenshot
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        page.screenshot(path=os.path.join(screenshots_dir, f'AI_{pnr}_preresult.png'))

        result_keywords = ['error', 'terminal', 'invalid', 'not found', 'cancelled',
                           'confirmed', 'itinerary', 'seat', 'payment failed', 'payment',
                           'booking cannot be found', 'search for a booking']
        
        start_time = time.time()
        final_text = ""
        while time.time() - start_time < 45:
            try:
                final_text = page.inner_text('body')
                text_lower = final_text.lower()
                if 'incapsula incident' in text_lower or 'request unsuccessful' in text_lower:
                    raise Exception("Imperva WAF blocked the API call after form submit")
                if any(kw in text_lower for kw in result_keywords) and len(final_text) > 100:
                    time.sleep(1.5)
                    final_text = page.inner_text('body')
                    break
            except Exception as e:
                if 'Imperva' in str(e):
                    raise
            time.sleep(0.5)

        text_lower = final_text.lower()

        # Save screenshot and raw text
        screenshot_path = os.path.join(screenshots_dir, f'AI_{pnr}_status.png')
        page.screenshot(path=screenshot_path)
        logger.info(f"Screenshot saved: {screenshot_path}")
        
        raw_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(raw_dir, f'AI_{pnr}_raw.txt'), 'w') as f:
            f.write(final_text)

        # Parse the status
        result = {'status': 'Error', 'detail': '', 'raw_text': final_text}

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

        if any(phrase in text_lower for phrase in [
            'payment failed', 'payment unsuccessful', 'payment has failed',
            'transaction failed', 'payment was not successful',
            'booking has been cancelled due to payment',
            'cancelled due to non-payment',
        ]):
            result['status'] = 'Cancelled'
            result['detail'] = 'Payment failed — booking was not completed. Flight effectively cancelled.'
        elif 'payment for this booking is incomplete' in text_lower or 'payment is incomplete' in text_lower:
            result['status'] = 'Payment Pending'
            result['detail'] = 'Payment incomplete — ticket not confirmed. Please complete payment on Air India.'
        elif any(phrase in text_lower for phrase in [
            'invalid', 'not found', 'no booking', 'cannot be found',
            'booking cannot be found', 'try again', 'no record'
        ]):
            result['status'] = 'Cancelled'
            result['detail'] = 'Booking not found on Air India — ticket likely cancelled.'
        elif 'access denied' in text_lower or 'incapsula' in text_lower:
            result['status'] = 'Error'
            result['detail'] = 'Air India website blocked the request. Will retry later.'
        elif _keyword_near_pnr('cancelled', pnr, final_text, window=300) or ('cancelled' in text_lower and text_lower.count('cancelled') > 1):
            result['status'] = 'Cancelled'
            result['detail'] = extract_status_detail(final_text, 'cancelled')
        elif _keyword_near_pnr('rescheduled', pnr, final_text, window=300):
            result['status'] = 'Rescheduled'
            result['detail'] = extract_status_detail(final_text, 'rescheduled')
        elif _keyword_near_pnr('delayed', pnr, final_text, window=300):
            result['status'] = 'Delayed'
            result['detail'] = extract_status_detail(final_text, 'delayed')
        elif _keyword_near_pnr('confirmed', pnr, final_text, window=300):
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(final_text)
        elif _keyword_near_pnr('completed', pnr, final_text, window=300) or _keyword_near_pnr('flown', pnr, final_text, window=300):
            result['status'] = 'Completed'
            result['detail'] = 'Flight has been completed.'
        elif any(kw in text_lower for kw in [
            'confirmed', 'booked', 'itinerary', 'e-ticket',
            'seat selection', 'add-ons', 'check-in', 'checkin'
        ]):
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(final_text)
        elif 'check-in' in text_lower or 'checkin' in text_lower:
            result['status'] = 'Check-in Open'
            result['detail'] = extract_booking_detail(final_text)
        else:
            if 'search for a booking' in text_lower and 'continue' in text_lower:
                raise Exception("Air India soft-blocked the request (form re-displayed without result). Will retry.")
            result['status'] = 'Checked'
            result['detail'] = final_text[:500] if final_text else 'Could not parse status'

        if result['status'] not in ('Not Found', 'Error', 'Cancelled'):
            result['flight_info'] = extract_flight_info_from_web(final_text, lastname)

        return result

    except Exception as e:
        logger.error(f"Error during PNR check: {e}")
        raise
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
        if browser:
            try:
                # We don't close the browser context because we connect over CDP
                browser.disconnect()
            except Exception:
                pass
        pw.stop()

def check_pnr_status(pnr, lastname):
    attempt = 1
    while attempt <= MAX_RETRIES:
        try:
            return _try_check_pnr(pnr, lastname, attempt)
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            attempt += 1
            if attempt <= MAX_RETRIES:
                _human_delay(3.0, 6.0)
    
    # If all attempts fail
    return {
        'status': 'Error',
        'detail': f"Failed to check PNR after {MAX_RETRIES} attempts. Last error: Check logs.",
        'raw_text': ""
    }

"""

full_content = new_header_and_logic + "\n" + extraction_code
with open('scraper_airindia.py', 'w') as f:
    f.write(full_content)
