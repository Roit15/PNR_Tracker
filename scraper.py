import json
import logging
import time
import re
import random
from typing import Dict, Any
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

# Akamai rate-limit settings
MAX_RETRIES = 2
BASE_BACKOFF_SECS = 45  # wait 45s, then 90s on retry

MYBOOKINGS_URL = "https://www.goindigo.in/account/my-bookings.html"


def check_pnr_status(pnr: str, last_name: str) -> Dict[str, Any]:
    """
    Use real installed Chrome via Playwright to check IndiGo PNR.
    Runs Akamai sensor JS natively — behaves exactly like a real user.
    Includes retry with backoff if Akamai blocks the request.
    """
    pnr = pnr.strip().upper()
    last_name = last_name.strip()

    for attempt in range(MAX_RETRIES + 1):
        try:
            result = _check_via_real_chrome(pnr, last_name)

            # If Akamai blocked, wait and retry
            if result.get('status') == 'Blocked':
                if attempt < MAX_RETRIES:
                    wait = BASE_BACKOFF_SECS * (attempt + 1) + random.uniform(5, 15)
                    logger.warning(f"Akamai block on PNR {pnr} (attempt {attempt+1}) — retrying in {wait:.0f}s")
                    time.sleep(wait)
                    continue
                else:
                    logger.error(f"Akamai block on PNR {pnr} — all retries exhausted")
                    return {"status": "Error", "detail": "IndiGo rate-limited (Akamai block). Try again later."}

            return result

        except Exception as e:
            logger.error(f"Chrome PNR check failed (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(BASE_BACKOFF_SECS * (attempt + 1))
                continue
            return {"status": "Error", "detail": f"Browser check failed: {str(e)}"}

    return {"status": "Error", "detail": "All retry attempts failed"}


def _check_via_real_chrome(pnr: str, last_name: str) -> Dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        try:
            # 0. Random pre-navigation delay to stagger parallel requests
            pre_delay = random.uniform(1.0, 4.0)
            time.sleep(pre_delay)

            # 1. Navigate
            logger.info(f"Loading IndiGo my-bookings page...")
            page.goto(MYBOOKINGS_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(5, 8))  # randomise wait for JS/Akamai sensor

            # 1.5. Check for Akamai block right after page load
            page_text_early = page.inner_text("body")
            if _is_akamai_blocked(page_text_early):
                logger.warning(f"Akamai block detected on page load for PNR {pnr}")
                return {"status": "Blocked", "detail": "Akamai Access Denied on page load", "raw_text": page_text_early[:2000]}

            # 2. Remove cookie consent overlay via JS
            page.evaluate("""
                document.querySelectorAll(
                    '[class*="consent"], [class*="cookie"], [class*="privacy"], .spcc_body'
                ).forEach(el => el.remove());
                document.querySelectorAll('.modal-backdrop, .overlay').forEach(el => el.remove());
                document.body.style.overflow = 'auto';
            """)
            time.sleep(random.uniform(0.8, 1.5))

            # 3. Fill PNR via keyboard (triggers React state)
            pnr_input = page.locator("input[name='pnr-booking-ref']")
            pnr_input.click(force=True)
            time.sleep(random.uniform(0.2, 0.5))
            page.keyboard.type(pnr, delay=random.randint(50, 90))
            time.sleep(random.uniform(0.3, 0.7))

            # 4. Fill LastName via keyboard
            ln_input = page.locator("input[name='email-last-name']")
            ln_input.click(force=True)
            time.sleep(random.uniform(0.2, 0.5))
            page.keyboard.type(last_name, delay=random.randint(50, 90))
            time.sleep(random.uniform(0.8, 1.5))

            # 5. Click Get Started
            btn = page.locator("button:has-text('Get Started')")
            btn.click(force=True, timeout=5000)
            logger.info("Clicked 'Get Started', waiting for result...")
            time.sleep(random.uniform(10, 15))

            # 6. Scrape page result
            page_text = page.inner_text("body")

            # 6.5. Check for Akamai block in result page
            if _is_akamai_blocked(page_text):
                logger.warning(f"Akamai block detected after form submit for PNR {pnr}")
                return {"status": "Blocked", "detail": "Akamai Access Denied after submit", "raw_text": page_text[:2000]}

            return _parse_page_text(page_text, pnr, last_name)

        finally:
            browser.close()


def _is_akamai_blocked(page_text: str) -> bool:
    """Detect Akamai WAF / CDN block pages."""
    block_indicators = [
        "Access Denied",
        "You don't have permission to access",
        "errors.edgesuite.net",
        "Reference #",
        "akamai",
    ]
    text_lower = page_text.lower()
    # Need at least 2 indicators to avoid false positives
    matches = sum(1 for ind in block_indicators if ind.lower() in text_lower)
    return matches >= 2


def _parse_page_text(page_text: str, pnr: str, last_name: str) -> Dict[str, Any]:
    """Parse the visible page text to extract flight details or detect errors."""

    # Check for error patterns
    error_patterns = [
        r"(?i)invalid.*record",
        r"(?i)pnr.*not.*found",
        r"(?i)booking.*not.*found",
        r"(?i)unable.*retrieve",
        r"(?i)no.*booking.*found",
        r"(?i)try\s+again",
    ]
    for pattern in error_patterns:
        if re.search(pattern, page_text):
            return {
                "status": "Not Found",
                "detail": "IndiGo page shows PNR not found",
                "raw_text": page_text[:2000]
            }

    # Check for success — look for "Your Itinerary" or flight details
    if "Your Itinerary" not in page_text and "Confirmed" not in page_text:
        if "Get Started" in page_text and "FIND YOUR BOOKING" in page_text:
            return {
                "status": "Error",
                "detail": "Form submission may have failed — still on landing page",
                "raw_text": page_text[:2000]
            }
        return {
            "status": "Unknown",
            "detail": "Could not determine PNR status",
            "raw_text": page_text[:2000]
        }

    # Extract flight details from page text
    result = {
        "status": "Confirmed",
        "detail": "",
        "flights": [],
        "passengers": [],
        "raw_text": page_text[:3000]
    }

    # Extract booking status
    status_match = re.search(r'\b(Confirmed|Cancelled|Waitlisted|Pending)\b', page_text)
    if status_match:
        result["status"] = status_match.group(1)

    # Extract PNR
    pnr_match = re.search(r'PNR:\s*\n?\s*([A-Z0-9]{6})', page_text)
    if pnr_match:
        result["pnr"] = pnr_match.group(1)

    # Extract route (e.g., "BKK\nBLR" or "DEL\nBOM")
    route_match = re.search(r'([A-Z]{3})\n([A-Z]{3})', page_text)
    if route_match:
        result["origin"] = route_match.group(1)
        result["destination"] = route_match.group(2)

    # Extract date
    date_match = re.search(r'(\d{1,2}\s+\w{3},?\s+\d{2,4})', page_text)
    if date_match:
        result["date"] = date_match.group(1)

    # Extract pax count
    pax_match = re.search(r'(\d+)\s*Pax', page_text)
    if pax_match:
        result["pax_count"] = int(pax_match.group(1))

    # Extract flight number
    flight_match = re.search(r'(6E\s*\d{3,4})', page_text)
    if flight_match:
        result["flight_number"] = flight_match.group(1)

    # Extract times
    dep_match = re.search(r'(\d{2}:\d{2})\n([A-Z]{3})-(.+?)(?:\n|$)', page_text)
    if dep_match:
        result["departure_time"] = dep_match.group(1)
        result["departure_airport"] = dep_match.group(3).strip()

    arr_match = re.search(r'Travel Time.*?\n(\d{2}:\d{2})\n([A-Z]{3})-(.+?)(?:\n|$)', page_text)
    if arr_match:
        result["arrival_time"] = arr_match.group(1)
        result["arrival_airport"] = arr_match.group(3).strip()

    # Extract duration
    dur_match = re.search(r'(\d+h\s*\d+m)', page_text)
    if dur_match:
        result["duration"] = dur_match.group(1)

    # Extract passenger names
    passenger_matches = re.findall(r'(Mr\.|Mrs\.|Ms\.|Miss)\s+([A-Za-z\s]+?)(?:\n|$)', page_text)
    for title, name in passenger_matches:
        result["passengers"].append(f"{title} {name.strip()}")

    # Build flight info
    flight = {}
    if result.get("origin") and result.get("destination"):
        flight["route"] = f"{result['origin']}-{result['destination']}"
    if result.get("flight_number"):
        flight["flight_number"] = result["flight_number"]
    if result.get("date"):
        flight["flight_date"] = result["date"]
    if result.get("departure_time"):
        flight["departure_time"] = result["departure_time"]
    if result.get("arrival_time"):
        flight["arrival_time"] = result["arrival_time"]
    if result.get("duration"):
        flight["duration"] = result["duration"]
    if result.get("passengers"):
        flight["passenger_name"] = result["passengers"][0]
    if result.get("pax_count"):
        flight["passenger_count"] = result["pax_count"]
    if flight:
        result["flights"].append(flight)

    pax_str = ", ".join(result.get("passengers", [last_name]))
    route_str = f"{result.get('origin', '?')}-{result.get('destination', '?')}"
    result["detail"] = f"{result['status']} | {route_str} | {result.get('date', '')} | {pax_str}"

    return result


import os
import random
import signal
import shutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

_USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
]

def _is_cloud():
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'

def _kill_driver(driver):
    if driver is None:
        return
    try:
        driver.quit()
    except Exception as e:
        pass

import chrome_launcher
def _create_stealth_driver():
    chrome_launcher.ensure_chrome_running()
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9224")
    
    driver = webdriver.Chrome(options=options)
    return driver

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        print(json.dumps(check_pnr_status(sys.argv[1], sys.argv[2]), indent=2))
