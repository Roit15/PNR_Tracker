"""
IndiGo PNR Scraper — Single Browser Session Approach.

KEY INSIGHT: Load the IndiGo page ONCE, then check multiple PNRs
by clearing and refilling the form fields WITHOUT reloading the page.
This means only 1 hit to Akamai's WAF regardless of how many PNRs we check.

The actual API call goes to api-prod-itinerary-skyplus6e.goindigo.in
(a different subdomain with no Akamai rate-limiting).
"""
import json
import logging
import time
import re
import random
from typing import Dict, Any, List, Tuple
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

MYBOOKINGS_URL = "https://www.goindigo.in/account/my-bookings.html"

# How long to wait between consecutive PNR checks (in one session)
INTER_CHECK_DELAY_MIN = 3
INTER_CHECK_DELAY_MAX = 6


def check_pnr_status(pnr: str, last_name: str) -> Dict[str, Any]:
    """
    Check a single IndiGo PNR. For bulk checks, use check_multiple_pnrs() instead.
    """
    results = check_multiple_pnrs([(pnr, last_name)])
    return results[0] if results else {"status": "Error", "detail": "No result returned"}


def check_multiple_pnrs(pnr_list: List[Tuple[str, str]], on_progress=None, stop_requested_fn=None) -> List[Dict[str, Any]]:
    """
    Check multiple IndiGo PNRs in a SINGLE browser session.
    
    Opens ONE Chrome window, loads the IndiGo page ONCE, then checks
    each PNR by clearing/refilling the form. Only 1 page load = 1 Akamai hit.
    
    Args:
        pnr_list: List of (pnr, last_name) tuples
        on_progress: Optional callback fn(pnr, last_name, result, index, total)
        stop_requested_fn: Optional fn() -> bool to check if stop was requested
    
    Returns:
        List of result dicts, one per PNR (same order as input)
    """
    if not pnr_list:
        return []
    
    results = []
    
    try:
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
                # ═══ PHASE 1: Load page ONCE ═══════════════════════════
                logger.info(f"Loading IndiGo page (single session for {len(pnr_list)} PNR(s))...")
                page.goto(MYBOOKINGS_URL, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(5, 8))

                # Check for Akamai block on initial load
                page_text = page.inner_text("body")
                if _is_akamai_blocked(page_text):
                    logger.error("Akamai blocked on initial page load!")
                    return [{"status": "Error", "detail": "Akamai blocked initial page load"} for _ in pnr_list]

                # Remove cookie consent overlay
                _dismiss_overlays(page)
                time.sleep(random.uniform(0.8, 1.5))

                # ═══ PHASE 2: Check each PNR using form clear+refill ═══
                for i, (pnr, last_name) in enumerate(pnr_list):
                    if stop_requested_fn and stop_requested_fn():
                        logger.info("Stop requested, halting IndiGo check.")
                        break

                    pnr = pnr.strip().upper()
                    last_name = last_name.strip()
                    
                    logger.info(f"  [{i+1}/{len(pnr_list)}] Checking PNR={pnr}, LastName={last_name}")
                    
                    try:
                        if i == 0:
                            # First PNR: just fill the empty form
                            result = _fill_and_submit(page, pnr, last_name)
                        else:
                            # Subsequent PNRs: navigate back and refill
                            result = _check_next_pnr(page, pnr, last_name)
                        
                        results.append(result)
                        logger.info(f"  [{i+1}/{len(pnr_list)}] PNR={pnr}: {result.get('status', 'Unknown')}")

                        if on_progress:
                            try:
                                on_progress(pnr, last_name, result, i, len(pnr_list))
                            except Exception as pe:
                                logger.warning(f"on_progress callback error: {pe}")
                        
                    except Exception as e:
                        logger.error(f"  Error checking PNR {pnr}: {e}")
                        err_res = {
                            "status": "Error",
                            "detail": f"Browser error: {str(e)}",
                            "raw_text": ""
                        }
                        results.append(err_res)
                        if on_progress:
                            try:
                                on_progress(pnr, last_name, err_res, i, len(pnr_list))
                            except Exception:
                                pass

                    # Random delay between checks (only if more PNRs to go)
                    if i < len(pnr_list) - 1:
                        if stop_requested_fn and stop_requested_fn():
                            break
                        delay = random.uniform(INTER_CHECK_DELAY_MIN, INTER_CHECK_DELAY_MAX)
                        logger.info(f"  Waiting {delay:.1f}s before next PNR...")
                        time.sleep(delay)

            finally:
                browser.close()

    except Exception as e:
        logger.error(f"Browser session failed: {e}")
        # Fill remaining results with errors
        while len(results) < len(pnr_list):
            results.append({"status": "Error", "detail": f"Session failed: {str(e)}"})

    return results


def _dismiss_overlays(page):
    """Remove cookie consent and other overlays."""
    try:
        page.evaluate("""
            document.querySelectorAll(
                '[class*="consent"], [class*="cookie"], [class*="privacy"], .spcc_body'
            ).forEach(el => el.remove());
            document.querySelectorAll('.modal-backdrop, .overlay').forEach(el => el.remove());
            document.body.style.overflow = 'auto';
        """)
    except Exception:
        pass


def _fill_and_submit(page, pnr: str, last_name: str) -> Dict[str, Any]:
    """Fill the form and submit for the first PNR check."""
    
    # Fill PNR
    pnr_input = page.locator("input[name='pnr-booking-ref']")
    pnr_input.click(force=True)
    time.sleep(random.uniform(0.2, 0.4))
    page.keyboard.type(pnr, delay=random.randint(50, 80))
    time.sleep(random.uniform(0.3, 0.6))

    # Fill LastName
    ln_input = page.locator("input[name='email-last-name']")
    ln_input.click(force=True)
    time.sleep(random.uniform(0.2, 0.4))
    page.keyboard.type(last_name, delay=random.randint(50, 80))
    time.sleep(random.uniform(0.5, 1.0))

    # Click Get Started
    btn = page.locator("button:has-text('Get Started')")
    btn.click(force=True, timeout=5000)
    logger.info("Clicked 'Get Started', waiting for result...")
    time.sleep(random.uniform(10, 14))

    # Read result
    page_text = page.inner_text("body")
    
    if _is_akamai_blocked(page_text):
        return {"status": "Error", "detail": "Akamai Access Denied after submit", "raw_text": page_text[:2000]}
    
    return _parse_page_text(page_text, pnr, last_name)


def _check_next_pnr(page, pnr: str, last_name: str) -> Dict[str, Any]:
    """
    Check the next PNR by navigating back to the form and refilling.
    Uses browser back + form refill instead of a full page reload.
    """
    # Try to find "Back" or navigate to the form again
    # Option 1: Click the back/modify link if available
    try:
        # Look for "Modify Booking" or back-to-form links
        back_link = page.locator("a:has-text('Back'), a:has-text('Modify'), button:has-text('Back')")
        if back_link.count() > 0:
            back_link.first.click(force=True)
            time.sleep(random.uniform(2, 4))
        else:
            # Option 2: Use browser history back
            page.go_back(wait_until="domcontentloaded", timeout=15000)
            time.sleep(random.uniform(3, 5))
    except Exception:
        # Option 3: Navigate to the URL directly (still reuses session/cookies)
        page.goto(MYBOOKINGS_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(4, 6))

    # Dismiss any overlays that reappear
    _dismiss_overlays(page)
    time.sleep(random.uniform(0.5, 1.0))

    # Check if we're blocked
    page_text = page.inner_text("body")
    if _is_akamai_blocked(page_text):
        return {"status": "Error", "detail": "Akamai blocked on form reload", "raw_text": page_text[:2000]}

    # Clear any existing form values and fill fresh
    try:
        pnr_input = page.locator("input[name='pnr-booking-ref']")
        pnr_input.click(force=True)
        time.sleep(0.2)
        # Triple-click to select all, then clear
        pnr_input.click(click_count=3, force=True)
        time.sleep(0.1)
        page.keyboard.press("Backspace")
        time.sleep(0.2)
        # Also clear via JS in case React state is stale
        page.evaluate("""
            const pnrInput = document.querySelector("input[name='pnr-booking-ref']");
            if (pnrInput) {
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(pnrInput, '');
                pnrInput.dispatchEvent(new Event('input', { bubbles: true }));
                pnrInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
            const lnInput = document.querySelector("input[name='email-last-name']");
            if (lnInput) {
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(lnInput, '');
                lnInput.dispatchEvent(new Event('input', { bubbles: true }));
                lnInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """)
        time.sleep(0.3)
    except Exception as e:
        logger.warning(f"Form clear failed (non-fatal): {e}")

    # Now fill and submit
    return _fill_and_submit(page, pnr, last_name)


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
    result["flight_info"] = result["flights"]

    pax_str = ", ".join(result.get("passengers", [last_name]))
    route_str = f"{result.get('origin', '?')}-{result.get('destination', '?')}"
    result["detail"] = f"{result['status']} | {route_str} | {result.get('date', '')} | {pax_str}"

    return result


# ── Legacy imports for backward compatibility with scraper.py ──────────
import os
import signal
import shutil

def _is_cloud():
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    
    if len(sys.argv) > 2:
        pnr = sys.argv[1]
        lastname = sys.argv[2]
        result = check_pnr_status(pnr, lastname)
        print(json.dumps(result, indent=2))
    else:
        # Demo: check multiple PNRs in one session
        test_pnrs = [
            ("OBVDWJ", "Kumar"),
        ]
        results = check_multiple_pnrs(test_pnrs)
        for r in results:
            print(json.dumps(r, indent=2))
