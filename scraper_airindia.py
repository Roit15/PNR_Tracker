"""
Air India PNR Status Scraper.
Uses Selenium with stealth mode to check flight status on airindia.com

Key design:
  - Same stealth approach as IndiGo scraper (shared driver utility)
  - Targets: https://www.airindia.com/in/en/manage/booking.html
  - Air India form: PNR + Last Name → Retrieve booking
  - Flight numbers: AI XXX pattern (vs IndiGo's 6E XXXX)
"""

import os
import ssl
import time
import logging
import re
import random
from datetime import datetime, timedelta

# Module-level SSL fix — must run BEFORE any uc/urllib HTTPS calls,
# and must persist across retries (uc.Chrome() can reset things).
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
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

AIRINDIA_HOME = "https://www.airindia.com/in/en.html"
AIRINDIA_URL = "https://www.airindia.com/in/en/manage/booking.html"
MAX_RETRIES = 2

# Rotate User-Agent strings to avoid fingerprint-based blocking
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
]


def _human_delay(min_s=1.0, max_s=3.0):
    """Sleep for a random duration to mimic human behavior."""
    time.sleep(random.uniform(min_s, max_s))


def _keyword_near_pnr(keyword, pnr_code, full_text, window=400):
    """Check if a keyword appears near the PNR code in the text."""
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


def _is_cloud():
    """Detect if running in cloud/Docker (Render, Railway, etc.)."""
    return os.getenv('RENDER') or os.getenv('DISPLAY') == ':99'


def _fix_ssl():
    """Patch macOS Python SSL so undetected-chromedriver can download its patcher."""
    import ssl
    # env vars don't help urllib — must patch the context factory directly
    ssl._create_default_https_context = ssl._create_unverified_context
    try:
        import certifi
        os.environ['SSL_CERT_FILE'] = certifi.where()
        os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
    except ImportError:
        pass


def _detect_chrome_version():
    """Detect installed Chrome version for uc.Chrome(version_main=...)."""
    import subprocess
    candidates = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium-browser',
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                out = subprocess.check_output([path, '--version'], timeout=5).decode()
                m = re.search(r'(\d+)\.', out)
                if m:
                    return int(m.group(1))
            except Exception:
                continue
    return None


def _create_stealth_driver():
    """Create a Chrome driver with undetected-chromedriver to bypass Imperva WAF."""
    _fix_ssl()

    # Try undetected-chromedriver first (strongest anti-detection)
    try:
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--lang=en-US,en;q=0.9')
        options.add_argument(f'--user-agent={random.choice(USER_AGENTS)}')
        
        # Use a persistent user data directory so cookies/session persist
        # This makes repeat visits look like a returning user, not a fresh bot
        user_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.chrome_profile_ai')
        os.makedirs(user_data_dir, exist_ok=True)
        options.add_argument(f'--user-data-dir={user_data_dir}')

        # Local: visible popup window (headless gets fingerprinted by Imperva)
        # Cloud: must be headless (no display)
        if _is_cloud():
            # Run headful inside Xvfb instead of headless
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            logger.info("Cloud mode: headful (Xvfb) + no-sandbox (undetected-chromedriver)")
        else:
            logger.info("Local mode: visible popup window (undetected-chromedriver)")

        # Match installed Chrome version → reduces fingerprint mismatch
        chrome_version = _detect_chrome_version()
        kwargs = {'options': options, 'use_subprocess': False}
        if chrome_version:
            kwargs['version_main'] = chrome_version
            logger.info(f"Using Chrome version_main={chrome_version}")

        driver = uc.Chrome(**kwargs)
        
        # Inject comprehensive anti-fingerprint JS via CDP
        # This defeats Imperva's client-side bot detection
        try:
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    // Override navigator.webdriver
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    
                    // Fake plugins array (real browsers have plugins)
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => {
                            const plugins = [1, 2, 3, 4, 5];
                            plugins.__proto__ = PluginArray.prototype;
                            return plugins;
                        }
                    });
                    
                    // Fake languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                    
                    // Chrome runtime
                    window.chrome = window.chrome || {};
                    window.chrome.runtime = window.chrome.runtime || {};
                    
                    // Fix permissions query
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                    
                    // Prevent canvas fingerprinting detection
                    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                    HTMLCanvasElement.prototype.toDataURL = function(type) {
                        if (type === 'image/webp' || this.width === 0 || this.height === 0) {
                            return originalToDataURL.apply(this, arguments);
                        }
                        const context = this.getContext('2d');
                        if (context) {
                            const shift = Math.random() * 0.01;
                            const imageData = context.getImageData(0, 0, this.width, this.height);
                            for (let i = 0; i < imageData.data.length; i += 4) {
                                imageData.data[i] = imageData.data[i] + (shift > 0.005 ? 1 : 0);
                            }
                            context.putImageData(imageData, 0, 0);
                        }
                        return originalToDataURL.apply(this, arguments);
                    };
                    
                    // Fix connection.rtt (bots often have rtt=0)
                    if (navigator.connection) {
                        Object.defineProperty(navigator.connection, 'rtt', {get: () => 100});
                    }
                    
                    // Prevent detection of automated window.open
                    const originalOpen = window.open;
                    window.open = function() {
                        return originalOpen.apply(this, arguments);
                    };
                '''
            })
            logger.info("CDP anti-fingerprint JS injected")
        except Exception as e:
            logger.warning(f"CDP injection failed (non-fatal): {e}")
        
        logger.info("Using undetected-chromedriver (Imperva bypass)")
        return driver

    except Exception as e:
        logger.warning(f"undetected-chromedriver failed ({e}), using selenium-stealth fallback")

    # Fallback: regular Selenium + selenium-stealth
    options = Options()
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_argument('--disable-infobars')
    options.add_argument('--lang=en-US,en;q=0.9')
    options.add_argument(f'--user-agent={random.choice(USER_AGENTS)}')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    # Local: visible popup window; Cloud: headless
    if _is_cloud():
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    else:
        logger.info("Local mode: visible popup window (selenium-stealth fallback)")

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        driver = webdriver.Chrome(options=options)

    # Remove webdriver flag
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        '''
    })

    # Apply selenium-stealth for deeper fingerprint masking
    try:
        from selenium_stealth import stealth
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="MacIntel",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True)
        logger.info("selenium-stealth applied successfully")
    except ImportError:
        logger.warning("selenium-stealth not available, using basic stealth only")
    except Exception as e:
        logger.warning(f"selenium-stealth error: {e}")

    return driver


def _dismiss_popups(driver, wait):
    """Try to dismiss cookie consent, search overlays, and other popups."""
    # 1. Air India specific cookie consent — "Accept All" button
    # The cookie banner uses text "Accept All" and blocks form interaction
    try:
        accept_btns = driver.find_elements(By.XPATH,
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "accept all")]')
        for btn in accept_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.5)
                logger.info("Dismissed Air India cookie consent via 'Accept All' button")
                break
    except Exception:
        pass

    # 2. Generic cookie consent buttons (fallback)
    cookie_selectors = [
        'button[id*="accept"]',
        'button[class*="accept"]',
        'button[id*="cookie"]',
        'a[id*="accept"]',
    ]
    for sel in cookie_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            if btn.is_displayed():
                btn.click()
                time.sleep(0.2)
                logger.info(f"Dismissed cookie popup: {sel}")
        except (NoSuchElementException, Exception):
            continue

    time.sleep(0.2)

    # 3. Close the "What are you looking for?" search overlay
    search_close_selectors = [
        'button[aria-label="Close"]',
        'button[aria-label="close"]',
        '.search-close',
        '.close-search',
        '.modal-close',
        'button[class*="close"]',
        '//button[contains(@class, "close")]',
        '//div[contains(@class, "search")]//button',
    ]
    for sel in search_close_selectors:
        try:
            if sel.startswith('//'):
                btns = driver.find_elements(By.XPATH, sel)
            else:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(0.2)
                    logger.info(f"Closed search/modal overlay: {sel}")
        except (NoSuchElementException, Exception):
            continue

    # 4. Remove any overlays via JS
    try:
        driver.execute_script("document.querySelector('.search-overlay, .overlay, .modal-backdrop')?.remove();")
        logger.info("Removed overlay elements via JS")
    except Exception:
        pass

    # 5. Remove the cookie banner container entirely if it's still visible
    try:
        driver.execute_script("""
            var cookieBanner = document.querySelector('.onetrust-consent-sdk, [id*="onetrust"], [class*="cookie-banner"], [class*="cookie-consent"]');
            if (cookieBanner) cookieBanner.remove();
            // Also try Air India's custom cookie element
            var els = document.querySelectorAll('[class*="cookieConsent"], [class*="cookie-settings"]');
            els.forEach(function(el) { el.remove(); });
        """)
    except Exception:
        pass


def _fill_input_angular(driver, element, value):
    """
    Fill an Angular Material input field properly.
    Angular's change detection requires both native events AND model updates.
    Simple send_keys() often fails because Angular doesn't see the change.
    """
    # First, click the element to focus it
    try:
        driver.execute_script("arguments[0].click();", element)
        time.sleep(0.2)
    except Exception:
        pass

    # Clear existing value
    element.clear()
    time.sleep(0.1)

    # Type characters with human-like delays
    for char in value:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))

    # Trigger Angular change detection via JS events
    driver.execute_script("""
        var el = arguments[0];
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.dispatchEvent(new Event('blur', {bubbles: true}));
    """, element)
    time.sleep(0.2)

    # Verify the value was set
    actual_value = element.get_attribute('value') or ''
    if actual_value.upper() != value.upper():
        # Fallback: set value via JavaScript and trigger events
        logger.warning(f"send_keys value mismatch (got '{actual_value}', expected '{value}'). Using JS fallback.")
        driver.execute_script("""
            var el = arguments[0];
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(el, arguments[1]);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new Event('blur', {bubbles: true}));
        """, element, value)
        time.sleep(0.3)
        actual_value = element.get_attribute('value') or ''
        if actual_value.upper() != value.upper():
            logger.error(f"JS fallback also failed: got '{actual_value}', expected '{value}'")
        else:
            logger.info(f"JS fallback succeeded: value = '{actual_value}'")


def _find_and_fill_form(driver, wait, pnr, lastname):
    """
    Find the manage booking form fields and fill them.
    Air India uses Angular Material components (ai-managebooking).
    Known selectors: name='pnr-ip', id='pnr-ip-id', name='lastname-ip', id='lastname-ip-id'
    """
    # Strategy 1: Known Air India Angular component selectors (most reliable)
    pnr_selectors = [
        'input[name="pnr-ip"]',           # Current Angular form
        'input#pnr-ip-id',                 # By ID
        'input[aria-label*="PNR"]',
        'input[aria-label*="Booking reference"]',
        'input[placeholder*="PNR"]',
        'input[placeholder*="Booking"]',
        'input[name*="pnr"]',
        'input[name*="booking"]',
        'input[id*="pnr"]',
        'input[id*="booking"]',
        'input[formcontrolname="pnrNumber"]',
    ]

    lastname_selectors = [
        'input[name="lastname-ip"]',       # Current Angular form
        'input#lastname-ip-id',            # By ID
        'input[aria-label="Last Name"]',
        'input[placeholder*="Last"]',
        'input[placeholder*="Surname"]',
        'input[name*="last"]',
        'input[name*="surname"]',
        'input[id*="last"]',
        'input[id*="surname"]',
        'input[formcontrolname="lastName"]',
    ]

    # Wait for the Angular form to render (look for the ai-managebooking element)
    try:
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, 'ai-managebooking, input[name="pnr-ip"], input[name*="pnr"]')) > 0)
        logger.info("Angular manage booking form detected")
    except TimeoutException:
        # Fallback: wait for any input
        try:
            wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, 'input')) > 1)
        except TimeoutException:
            pass

    # Fill PNR
    pnr_input = None
    for sel in pnr_selectors:
        try:
            pnr_input = driver.find_element(By.CSS_SELECTOR, sel)
            if pnr_input.is_displayed():
                logger.info(f"Found PNR input: {sel}")
                break
            pnr_input = None
        except NoSuchElementException:
            continue

    if not pnr_input:
        # Fallback: find all visible text inputs and use the first one
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input:not([type])')
        visible_inputs = [inp for inp in inputs if inp.is_displayed()]
        if len(visible_inputs) >= 1:
            pnr_input = visible_inputs[0]
            logger.info("PNR input found via fallback (first visible text input)")
        else:
            raise Exception("Could not find PNR input field")

    # Use Angular-aware filling
    _fill_input_angular(driver, pnr_input, pnr)
    _human_delay(0.3, 0.8)

    # Fill Last Name
    lastname_input = None
    for sel in lastname_selectors:
        try:
            lastname_input = driver.find_element(By.CSS_SELECTOR, sel)
            if lastname_input.is_displayed():
                logger.info(f"Found Last Name input: {sel}")
                break
            lastname_input = None
        except NoSuchElementException:
            continue

    if not lastname_input:
        # Fallback: second visible text input
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input:not([type])')
        visible_inputs = [inp for inp in inputs if inp.is_displayed() and inp != pnr_input]
        if visible_inputs:
            lastname_input = visible_inputs[0]
            logger.info("Last Name input found via fallback (second visible text input)")
        else:
            raise Exception("Could not find Last Name input field")

    # Use Angular-aware filling
    _fill_input_angular(driver, lastname_input, lastname)
    _human_delay(0.3, 0.8)

    # Verify both fields have values before submitting
    pnr_val = pnr_input.get_attribute('value') or ''
    ln_val = lastname_input.get_attribute('value') or ''
    if not pnr_val or not ln_val:
        logger.error(f"Form verification failed: PNR='{pnr_val}', LastName='{ln_val}'")
        raise Exception(f"Form fields not filled properly (PNR='{pnr_val}', LastName='{ln_val}'). Angular binding may have failed.")
    logger.info(f"Form verified: PNR='{pnr_val}', LastName='{ln_val}'")

    # Click submit using JavaScript to avoid overlay interception
    submit_btn = None
    # Prioritize the Air India specific class, then text-based selectors
    submit_selectors = [
        'button.form-btn.booking-flight-btn',  # Air India Angular component
        'button.form-btn',                      # Simplified class
        '//button[contains(text(), "Submit")]',
        '//button[contains(text(), "submit")]',
        'button[type="submit"]',
        '//button[contains(text(), "Retrieve")]',
        '//button[contains(text(), "Search")]',
        '//button[contains(text(), "Find")]',
        'button[class*="submit"]',
        'button[class*="retrieve"]',
        'button[class*="search"]',
        'input[type="submit"]',
    ]
    for sel in submit_selectors:
        try:
            if sel.startswith('//'):
                submit_btn = driver.find_element(By.XPATH, sel)
            else:
                submit_btn = driver.find_element(By.CSS_SELECTOR, sel)
            if submit_btn.is_displayed() and submit_btn.is_enabled():
                logger.info(f"Found submit button: {sel}")
                break
            submit_btn = None
        except NoSuchElementException:
            continue

    if not submit_btn:
        raise Exception("Could not find submit/retrieve button")

    _human_delay(0.3, 0.8)
    # Use JavaScript click to bypass any overlapping elements
    driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
    _human_delay(0.3, 0.6)
    driver.execute_script("arguments[0].click();", submit_btn)
    logger.info("Clicked submit button via JavaScript")


def _try_check_pnr(pnr, lastname, attempt=1):
    """
    Single attempt to check Air India PNR status via a fresh browser.
    Returns result dict or raises Exception on failure.
    Uses CDP Network interception to capture the actual API response,
    which is more reliable than parsing the DOM (which can show fake WAF responses).
    """
    driver = _create_stealth_driver()
    try:
        logger.info(f"[AI Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr}")

        # Enable CDP Network domain to capture XHR responses
        # The Angular app calls an API endpoint after form submit — we intercept that
        api_responses = []
        try:
            driver.execute_cdp_cmd('Network.enable', {})
            logger.info("CDP Network interception enabled")
        except Exception as e:
            logger.warning(f"CDP Network.enable failed (non-fatal): {e}")

        # Go to homepage first to get proper session cookies, then to manage booking
        logger.info("Navigating to homepage to initialize session...")
        driver.get(AIRINDIA_HOME)
        _human_delay(4.0, 7.0)
        
        # Simulate human-like behavior: random scroll and mouse movement
        try:
            driver.execute_script("""
                window.scrollTo(0, Math.random() * 300);
                setTimeout(() => window.scrollTo(0, 0), 500);
            """)
        except Exception:
            pass
        _human_delay(1.0, 3.0)
        
        logger.info("Navigating to manage booking page...")
        driver.get(AIRINDIA_URL)
        _human_delay(5.0, 9.0)  # longer delay to mimic real user

        # Check if page got blocked
        page_text_check = driver.find_element(By.TAG_NAME, 'body').text.lower()
        if 'incapsula incident' in page_text_check or 'request unsuccessful' in page_text_check:
            raise Exception("Imperva WAF blocked the page load — will retry with fresh browser")
        if 'access denied' in page_text_check:
            raise Exception("Access Denied on manage booking — Imperva WAF blocked the request")

        wait = WebDriverWait(driver, 40)

        # Dismiss any popups/cookie banners
        _dismiss_popups(driver, wait)
        _human_delay(0.5, 1.5)

        # Dismiss again in case something re-appeared
        _dismiss_popups(driver, wait)
        _human_delay(0.5, 1.0)

        # Inject XHR/fetch interceptor to capture API responses
        # This captures the REAL API response before the DOM is potentially tampered by WAF
        try:
            driver.execute_script("""
                window.__aiApiResponses = [];
                
                // Intercept fetch() calls
                const originalFetch = window.fetch;
                window.fetch = function() {
                    return originalFetch.apply(this, arguments).then(response => {
                        const url = (typeof arguments[0] === 'string') ? arguments[0] : arguments[0]?.url || '';
                        if (url.includes('booking') || url.includes('retrieve') || url.includes('cbiz') || url.includes('manage')) {
                            response.clone().text().then(text => {
                                try {
                                    window.__aiApiResponses.push({
                                        url: url,
                                        status: response.status,
                                        data: text,
                                        timestamp: Date.now()
                                    });
                                } catch(e) {}
                            });
                        }
                        return response;
                    });
                };
                
                // Intercept XMLHttpRequest
                const originalXHROpen = XMLHttpRequest.prototype.open;
                const originalXHRSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.open = function(method, url) {
                    this.__aiUrl = url;
                    return originalXHROpen.apply(this, arguments);
                };
                XMLHttpRequest.prototype.send = function() {
                    this.addEventListener('load', function() {
                        const url = this.__aiUrl || '';
                        if (url.includes('booking') || url.includes('retrieve') || url.includes('cbiz') || url.includes('manage')) {
                            try {
                                window.__aiApiResponses.push({
                                    url: url,
                                    status: this.status,
                                    data: this.responseText,
                                    timestamp: Date.now()
                                });
                            } catch(e) {}
                        }
                    });
                    return originalXHRSend.apply(this, arguments);
                };
            """)
            logger.info("XHR/fetch interceptor injected")
        except Exception as e:
            logger.warning(f"XHR interceptor injection failed (non-fatal): {e}")

        # Find and fill the form
        _find_and_fill_form(driver, wait, pnr, lastname)

        # Save pre-result screenshot for debugging
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        driver.save_screenshot(os.path.join(screenshots_dir, f'AI_{pnr}_preresult.png'))

        # Wait for results — try to capture the XHR API response first
        # The Angular app makes an API call to check the booking
        result_keywords = ['error', 'terminal', 'invalid', 'not found', 'cancelled',
                           'confirmed', 'itinerary', 'seat', 'payment failed', 'payment',
                           'booking cannot be found', 'search for a booking',
                           'booking not found', 'manage your booking', 'your booking']
        start_time = time.time()
        page_text = ""
        api_data = None
        
        while time.time() - start_time < 45:
            try:
                # Try to capture API responses via CDP
                try:
                    api_data = driver.execute_script("""
                        // Intercept XHR/fetch responses stored by our hook
                        if (window.__aiApiResponses && window.__aiApiResponses.length > 0) {
                            return window.__aiApiResponses;
                        }
                        return null;
                    """)
                except Exception:
                    pass
                
                page_text = driver.find_element(By.TAG_NAME, 'body').text
                text_lower = page_text.lower()
                # Imperva block — bail out fast and let retry handle it
                if 'incapsula incident' in text_lower or 'request unsuccessful' in text_lower:
                    raise Exception("Imperva WAF blocked the API call after form submit")
                if any(kw in text_lower for kw in result_keywords) and len(page_text) > 100:
                    time.sleep(1.5)  # Give it time to fully render (error banner + modal)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                    break
            except Exception as e:
                if 'Imperva' in str(e):
                    raise
            time.sleep(0.5)

        text_lower = page_text.lower()

        # Log and save any captured API responses for debugging
        if api_data:
            logger.info(f"Captured {len(api_data)} API response(s) via XHR/fetch interceptor")
            for i, resp in enumerate(api_data):
                logger.info(f"  API[{i}]: URL={resp.get('url', '?')}, status={resp.get('status', '?')}, len={len(resp.get('data', ''))}")
            # Save API responses for debugging
            raw_dir = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(raw_dir, f'AI_{pnr}_api.json'), 'w') as f:
                import json as _json
                _json.dump(api_data, f, indent=2)
        else:
            logger.warning("No API responses captured — WAF may be blocking at network level")

        # Save screenshot and raw text BEFORE modal handling (for debugging every attempt)
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f'AI_{pnr}_status.png')
        driver.save_screenshot(screenshot_path)
        logger.info(f"Screenshot saved: {screenshot_path}")
        raw_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(raw_dir, f'AI_{pnr}_raw.txt'), 'w') as f:
            f.write(page_text)

        # Check if the secondary modal "Search for a booking" appeared.
        # Air India's flow: first form submit triggers an API call, which returns:
        #   Case A: Error banner ("1 ERROR\n...") + "Search for a booking" modal below
        #   Case B: Just the "Search for a booking" modal (soft block / no response)
        #   Case C: Actual booking details (itinerary page)
        if 'search for a booking' in text_lower and 'continue' in text_lower:
            # Check if there's an error banner ABOVE the modal (Case A)
            # Error banners contain text like "1 ERROR", "The payment for this booking...",
            # "Your booking cannot be found", etc.
            has_error_banner = (
                'error' in text_lower and (
                    'payment' in text_lower or
                    'booking cannot be found' in text_lower or
                    'cannot be found' in text_lower or
                    'try again' in text_lower or
                    'incomplete' in text_lower
                )
            )

            if has_error_banner:
                # Case A: We already have a real result in the error banner.
                # Don't re-submit — just parse the error text we already have.
                logger.info("Secondary modal with ERROR banner detected — parsing error result directly")
                # page_text already contains the error banner text, parse it below.
            else:
                # Case B: Modal appeared with NO error banner.
                # Air India silently rejected our submission (soft block).
                # Try filling the modal form and clicking Continue.
                logger.info("Secondary modal detected WITHOUT error banner — attempting modal form submit...")
                try:
                    _find_and_fill_form(driver, wait, pnr, lastname)
                    # Click the Continue button specifically
                    continue_btns = driver.find_elements(By.XPATH,
                        '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "continue")]')
                    for btn in continue_btns:
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].click();", btn)
                            logger.info("Clicked Continue button on secondary modal")
                            break

                    # Wait for results after modal submit
                    start_time = time.time()
                    while time.time() - start_time < 15:
                        try:
                            page_text = driver.find_element(By.TAG_NAME, 'body').text
                            text_lower = page_text.lower()
                            # Check for Imperva block
                            if 'incapsula incident' in text_lower or 'request unsuccessful' in text_lower:
                                raise Exception("Imperva WAF blocked after modal submit")
                            # Check for error banner appearing
                            if 'error' in text_lower and ('payment' in text_lower or 'cannot be found' in text_lower or 'incomplete' in text_lower):
                                time.sleep(1)
                                page_text = driver.find_element(By.TAG_NAME, 'body').text
                                logger.info("Error banner appeared after modal submit")
                                break
                            # Check for real booking results
                            if any(kw in text_lower for kw in ['itinerary', 'seat', 'confirmed', 'terminal', 'cancelled']):
                                if 'search for a booking' not in text_lower:
                                    time.sleep(1)
                                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                                    logger.info("Booking details page loaded after modal submit")
                                    break
                        except Exception as e:
                            if 'Imperva' in str(e) or 'WAF' in str(e):
                                raise
                        time.sleep(0.5)

                    # Check if we're still stuck on the form (soft block persists)
                    final_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                    if 'search for a booking' in final_text and 'continue' in final_text:
                        if 'error' not in final_text and 'payment' not in final_text and 'cannot be found' not in final_text:
                            logger.warning("Still stuck on Search for a booking form — soft block by Air India")
                            raise Exception("Air India soft-blocked the request (form re-displayed without result). Will retry.")

                except Exception as e:
                    if 'soft-blocked' in str(e).lower() or 'Imperva' in str(e) or 'WAF' in str(e):
                        raise
                    logger.warning(f"Failed to handle secondary modal: {e}")

        # Re-read page_text after modal handling (may have changed)
        page_text = driver.find_element(By.TAG_NAME, 'body').text

        # Save final screenshot after modal handling
        driver.save_screenshot(screenshot_path)
        with open(os.path.join(raw_dir, f'AI_{pnr}_raw.txt'), 'w') as f:
            f.write(page_text)

        # Parse the status
        result = {'status': 'Error', 'detail': '', 'raw_text': page_text}
        text_lower = page_text.lower()

        # Helper: check keyword near PNR in text
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

        # --- Form-fill failure detection ---
        # If the page still shows validation errors, the form was never submitted successfully
        if ('pnr is required' in text_lower or 'last name is required' in text_lower) and \
           'booking not found' not in text_lower and 'manage booking' in text_lower:
            raise Exception("Form fill failed — validation errors present ('PNR is required' / 'Last Name is required'). Will retry.")

        # PNR format validation error from Air India
        if 'pnr is not valid' in text_lower:
            result['status'] = 'Error'
            result['detail'] = 'PNR format is not valid according to Air India. Please verify the PNR code.'

        # Status detection
        # Booking found but cannot be modified online (often past/completed or agency-locked)
        elif 'your booking cannot be modified online' in text_lower:
            result['status'] = 'Confirmed'
            result['detail'] = 'Booking found (cannot be modified online). For further assistance, contact Air India support.'

        # "MANAGE YOUR BOOKING" with flight details — confirmed booking
        elif 'manage your booking' in text_lower and 'booking reference' in text_lower and pnr.upper() in page_text.upper():
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

        # Payment FAILED → treat as Cancelled (ticket was never issued)
        elif any(phrase in text_lower for phrase in [
            'payment failed', 'payment unsuccessful', 'payment has failed',
            'transaction failed', 'payment was not successful',
            'booking has been cancelled due to payment',
            'cancelled due to non-payment',
        ]):
            result['status'] = 'Cancelled'
            result['detail'] = 'Payment failed — booking was not completed. Flight effectively cancelled.'

        # Payment INCOMPLETE → still a chance to complete payment
        elif 'payment for this booking is incomplete' in text_lower or \
             'payment is incomplete' in text_lower:
            result['status'] = 'Payment Pending'
            result['detail'] = 'Payment incomplete — ticket not confirmed. Please complete payment on Air India.'

        # BOOKING NOT FOUND — clear response from Air India
        elif 'booking not found' in text_lower:
            result['status'] = 'Not Found'
            result['detail'] = 'Booking not found on Air India. The PNR may have expired, been cancelled, or is a codeshare booking.'

        elif any(phrase in text_lower for phrase in [
            'invalid', 'not found', 'no booking', 'cannot be found',
            'booking cannot be found', 'no record'
        ]):
            result['status'] = 'Not Found'
            result['detail'] = 'Booking not found on Air India. The PNR may have expired, been cancelled, or is a codeshare booking.'

        elif 'access denied' in text_lower or 'incapsula' in text_lower:
            result['status'] = 'Error'
            result['detail'] = 'Air India website blocked the request. Will retry later.'

        elif _keyword_near_pnr('cancelled', pnr, page_text, window=300) or \
             'cancelled' in text_lower and text_lower.count('cancelled') > 1:
            result['status'] = 'Cancelled'
            result['detail'] = extract_status_detail(page_text, 'cancelled')

        elif _keyword_near_pnr('rescheduled', pnr, page_text, window=300):
            result['status'] = 'Rescheduled'
            result['detail'] = extract_status_detail(page_text, 'rescheduled')

        elif _keyword_near_pnr('delayed', pnr, page_text, window=300):
            result['status'] = 'Delayed'
            result['detail'] = extract_status_detail(page_text, 'delayed')

        elif _keyword_near_pnr('confirmed', pnr, page_text, window=300):
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

        elif _keyword_near_pnr('completed', pnr, page_text, window=300) or \
             _keyword_near_pnr('flown', pnr, page_text, window=300):
            result['status'] = 'Completed'
            result['detail'] = 'Flight has been completed.'

        elif any(kw in text_lower for kw in [
            'confirmed', 'booked', 'itinerary', 'e-ticket',
            'seat selection', 'add-ons', 'check-in', 'checkin'
        ]):
            result['status'] = 'Confirmed'
            result['detail'] = extract_booking_detail(page_text)

        elif 'check-in' in text_lower or 'checkin' in text_lower:
            result['status'] = 'Check-in Open'
            result['detail'] = extract_booking_detail(page_text)

        else:
            # Check if we're still stuck on the "Search for a booking" form
            # (means the submission never went through — soft block)
            if 'search for a booking' in text_lower and 'booking reference' in text_lower and 'continue' in text_lower:
                raise Exception("Air India soft-blocked the request (form re-displayed without result). Will retry.")
            # Check if page is still showing the manage booking form with no result
            if 'manage booking' in text_lower and 'submit' in text_lower and len(page_text) < 500:
                raise Exception("Page still showing empty form — submission may not have worked. Will retry.")
            result['status'] = 'Checked'
            result['detail'] = page_text[:500] if page_text else 'Could not parse status'

        # Extract flight info for confirmed/valid bookings
        if result['status'] not in ('Not Found', 'Error'):
            result['flight_info'] = extract_flight_info_from_web(page_text, lastname)

        return result

    finally:
        from scraper import _kill_driver
        _kill_driver(driver)


def extract_flight_info_from_web(text: str, lastname: str) -> dict:
    """Extract flight details from Air India's retrieved booking page text."""
    info = {
        'flight_date': '',
        'route': '',
        'flight_number': '',
        'departure_time': '',
        'arrival_time': '',
        'passenger_name': '',
        'passenger_count': 1,
    }

    lines = text.split('\n')

    # Passenger Count
    # Air India puts "Passenger", "Passengers" and lists "Adult", "Child".
    # Since names are listed with titles, we can count the occurrences of "Adult", "Child", "Infant" or titles.
    # Or count the number of passengers listed under "Passengers".
    # Let's count "Adult", "Child", "Infant" keywords.
    pax_count = 0
    pax_types = re.findall(r'\b(Adult|Child|Infant)\b', text, re.IGNORECASE)
    if pax_types:
        pax_count = len(pax_types)
    else:
        # Fallback: Count titles
        pax_count = len(re.findall(r'\b(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+[A-Za-z]+', text, re.IGNORECASE))
    
    if pax_count > 0:
        info['passenger_count'] = pax_count

    # Passenger name: look for lastname
    for line in lines:
        if lastname.lower() in line.lower():
            # Match "Mr/Ms/Mrs First Last"
            m = re.search(r'(?i)\b(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+([A-Za-z\s]+?\s+' + re.escape(lastname) + r')\b', line)
            if m:
                info['passenger_name'] = m.group(1).strip()
                break
            # Simple match
            m2 = re.search(r'(?i)\b([A-Za-z]+\s+(?:[A-Za-z]+\s+)?' + re.escape(lastname) + r')\b', line)
            if m2:
                info['passenger_name'] = m2.group(1).strip()
                break

    # Flight Number: AI XXX or AI-XXX
    fn_match = re.search(r'(AI[\s-]*\d{1,4})', text)
    if fn_match:
        fn = fn_match.group(1).replace('-', ' ')
        # Normalize to "AI 123"
        fn = re.sub(r'AI\s*', 'AI ', fn)
        info['flight_number'] = fn.strip()

    # Flight Date: Look for dates in flight context, NOT date of birth
    # Air India shows: "03 OCT" or "TUE, 28 APR 26" or "27 Apr 2026"
    # DOB is shown as "Date of Birth\n06 Apr 1997" — we must skip dates near "Date of Birth"
    lines = text.split('\n')
    current_year = datetime.now().year

    # Strategy 1: Look for short date format near flight info ("03 OCT", "28 APR")
    # These appear in the booking details section, not DOB
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        # Match "DD MON" without year (Air India's flight date format)
        short_date = re.match(r'^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$', line_stripped, re.IGNORECASE)
        if short_date:
            # Check this isn't near "Date of Birth" (within 2 lines)
            nearby_text = ' '.join(lines[max(0, i-2):i]).lower()
            if 'date of birth' in nearby_text or 'dob' in nearby_text:
                continue
            day, mon = short_date.group(1), short_date.group(2)
            # Assume current year or next year
            try:
                dt = datetime.strptime(f'{day} {mon} {current_year}', '%d %b %Y')
                if dt < datetime.now() - timedelta(days=180):
                    dt = dt.replace(year=current_year + 1)
                info['flight_date'] = dt.strftime('%Y-%m-%d')
                break
            except Exception:
                continue

    # Strategy 2: Look for "DAY, DD MON YY" format (e.g., "TUE, 28 APR 26")
    if not info['flight_date']:
        for i, line in enumerate(lines):
            m = re.search(r'(?:MON|TUE|WED|THU|FRI|SAT|SUN),?\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:,?\s+(\d{2,4}))?', line, re.IGNORECASE)
            if m:
                nearby_text = ' '.join(lines[max(0, i-2):i]).lower()
                if 'date of birth' in nearby_text or 'dob' in nearby_text:
                    continue
                day, mon = m.group(1), m.group(2)
                year = m.group(3) if m.group(3) else str(current_year)
                if len(year) == 2:
                    year = '20' + year
                try:
                    dt = datetime.strptime(f'{day} {mon} {year}', '%d %b %Y')
                    # Skip if year is more than 5 years in the past (likely DOB)
                    if dt.year < current_year - 5:
                        continue
                    info['flight_date'] = dt.strftime('%Y-%m-%d')
                    break
                except Exception:
                    continue

    # Strategy 3: Full date with year ("27 Apr 2026") — skip if near DOB
    if not info['flight_date']:
        for m in re.finditer(r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),?\s*(\d{2,4})', text, re.IGNORECASE):
            day, mon, year = m.group(1), m.group(2), m.group(3)
            if len(year) == 2:
                year = '20' + year
            try:
                dt = datetime.strptime(f'{day} {mon} {year}', '%d %b %Y')
                # Skip dates more than 5 years in the past (DOB)
                if dt.year < current_year - 5:
                    continue
                # Check if this is near "Date of Birth" context
                pos = m.start()
                before_text = text[max(0, pos - 100):pos].lower()
                if 'date of birth' in before_text or 'dob' in before_text:
                    continue
                info['flight_date'] = dt.strftime('%Y-%m-%d')
                break
            except Exception:
                continue

    if not info['flight_date']:
        # Try ISO format
        iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if iso_match:
            info['flight_date'] = iso_match.group(1)

    # Route: 3-letter codes like DEL - BOM or DEL-BOM
    route_match = re.search(r'([A-Z]{3})\s*[-–→]\s*([A-Z]{3})', text)
    if route_match:
        info['route'] = f"{route_match.group(1)}-{route_match.group(2)}"
    else:
        # Look for standalone 3-letter codes on separate lines
        codes = re.findall(r'^([A-Z]{3})$', text, re.MULTILINE)
        if len(codes) >= 2:
            info['route'] = f"{codes[0]}-{codes[1]}"

    # Times: HH:MM format
    times = re.findall(r'\b(\d{2}:\d{2})\b', text)
    if times:
        info['departure_time'] = times[0]
        if len(times) >= 2:
            info['arrival_time'] = times[1]

    return info


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
        'cookie', 'privacy', 'terms', 'maharaja club', 'sign in', 'sign up',
        'gift card', 'cargo', 'newsletter', 'download app', 'sitemap',
        'copyright', 'fare rules', 'add-ons', 'route map', 'popular flight',
        'contact us', 'faq', 'feedback', 'e-store', 'exclusive deals',
        'partner airline', 'supplier corner', 'travel agent',
    ]

    lines = text.split('\n')
    details = []
    good_keywords = ['terminal', 'gate', 'boarding', 'seat', 'baggage']

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


def _try_check_pnr_playwright(pnr, lastname, attempt=1):
    """
    Check Air India PNR using Playwright + real Google Chrome with stealth patches.
    Uses Chrome's actual binary with a persistent profile, making it nearly
    indistinguishable from a real user browsing session.
    """
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import stealth_sync
    except ImportError:
        stealth_sync = None

    logger.info(f"[AI-PW Attempt {attempt}/{MAX_RETRIES}] Checking PNR: {pnr} via Playwright + real Chrome")

    pw = sync_playwright().start()
    context = None
    page = None
    try:
        try:
            context = pw.chromium.launch_persistent_context(
                user_data_dir="/tmp/pnr-chrome-stealth",
                headless=False,
                channel="chrome",  # Use real Google Chrome, not Playwright Chromium
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                ignore_default_args=["--enable-automation"],
            )
        except Exception as e:
            pw.stop()
            raise Exception(f"Could not launch Chrome persistent context: {e}") from e

        # Persistent context already has a default page
        page = context.pages[0] if context.pages else context.new_page()

        # Apply stealth patches to hide automation indicators
        if stealth_sync:
            stealth_sync(page)
            logger.info("Stealth patches applied")

        # Navigate to manage booking page
        logger.info("Navigating to manage booking page...")
        page.goto(AIRINDIA_URL, wait_until='domcontentloaded', timeout=60000)
        _human_delay(5.0, 9.0)

        # Check if page got blocked
        page_text = page.inner_text('body').lower()
        if 'incapsula incident' in page_text or 'request unsuccessful' in page_text or 'access denied' in page_text:
            raise Exception("Imperva WAF blocked the page load")

        # Dismiss cookie banner
        try:
            cookie_btn = page.locator('#onetrust-accept-btn-handler')
            if cookie_btn.is_visible(timeout=3000):
                cookie_btn.click()
                logger.info("Dismissed cookie banner")
                _human_delay(0.5, 1.0)
        except Exception:
            pass

        # Fill the form using JS native setter (avoids Angular Material overlay blocking clicks)
        try:
            page.evaluate(f"""
                (function() {{
                    var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    
                    var pnrEl = document.querySelector("input[name='pnr-ip']");
                    var lnEl = document.querySelector("input[name='lastname-ip']");
                    
                    if (pnrEl) {{
                        pnrEl.focus();
                        nativeSetter.call(pnrEl, '');
                        pnrEl.dispatchEvent(new Event('input', {{bubbles: true}}));
                        nativeSetter.call(pnrEl, '{pnr}');
                        pnrEl.dispatchEvent(new Event('input', {{bubbles: true}}));
                        pnrEl.dispatchEvent(new Event('change', {{bubbles: true}}));
                        pnrEl.dispatchEvent(new Event('blur', {{bubbles: true}}));
                    }}
                    
                    if (lnEl) {{
                        lnEl.focus();
                        nativeSetter.call(lnEl, '');
                        lnEl.dispatchEvent(new Event('input', {{bubbles: true}}));
                        nativeSetter.call(lnEl, '{lastname}');
                        lnEl.dispatchEvent(new Event('input', {{bubbles: true}}));
                        lnEl.dispatchEvent(new Event('change', {{bubbles: true}}));
                        lnEl.dispatchEvent(new Event('blur', {{bubbles: true}}));
                    }}
                }})();
            """)
            _human_delay(0.5, 1.0)
            
            # Verify form values
            pnr_val = page.locator("input[name='pnr-ip']").input_value()
            ln_val = page.locator("input[name='lastname-ip']").input_value()
            logger.info(f"Form filled: PNR='{pnr_val}', LastName='{ln_val}'")
            
            if pnr_val != pnr or ln_val.lower() != lastname.lower():
                raise Exception(f"Form fill mismatch: PNR='{pnr_val}', LastName='{ln_val}'")
        except Exception as e:
            raise Exception(f"Could not fill form: {e}")

        _human_delay(0.3, 0.8)

        # Click submit
        try:
            submit_btn = page.locator("button.form-btn.booking-flight-btn, button.bi-submit-btn, button[type='submit']").first
            submit_btn.scroll_into_view_if_needed()
            _human_delay(0.2, 0.5)
            submit_btn.click()
            logger.info("Clicked submit button")
        except Exception:
            # JS click fallback
            page.evaluate("""
                var btn = document.querySelector('button.form-btn.booking-flight-btn') || 
                          document.querySelector('button.bi-submit-btn') || 
                          document.querySelector('button[type="submit"]');
                if (btn) btn.click();
            """)
            logger.info("Clicked submit via JS fallback")

        # Save pre-result screenshot
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)

        # Wait for results
        result_keywords = ['error', 'terminal', 'invalid', 'not found', 'cancelled',
                           'confirmed', 'itinerary', 'seat', 'payment failed', 'payment',
                           'booking cannot be found', 'search for a booking',
                           'booking not found', 'manage your booking', 'your booking']
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

        # Check for form validation errors → form fill failed
        if 'pnr is required' in text_lower or 'last name is required' in text_lower:
            raise Exception("Form validation errors detected — form fields not filled correctly")

        # Parse the status using the same logic
        return _parse_status(pnr, lastname, final_text, text_lower)

    except Exception as e:
        logger.error(f"Playwright check error: {e}")
        raise
    finally:
        # Close the tab we opened (and any extras) so no windows remain visible
        if context:
            try:
                for p in context.pages:
                    try:
                        p.close()
                    except:
                        pass
                context.close()
            except Exception:
                pass
        pw.stop()


def _parse_status(pnr, lastname, page_text, text_lower):
    """Parse the page text into a status result dict. Shared between Selenium and Playwright paths."""
    result = {'status': 'Error', 'detail': '', 'raw_text': page_text}

    # ----- CLEAR STATUSES (no proximity check needed) -----
    # Payment failures
    if any(phrase in text_lower for phrase in [
        'payment failed', 'payment unsuccessful', 'payment has failed',
        'transaction failed', 'payment was not successful',
        'booking has been cancelled due to payment',
        'cancelled due to non-payment',
    ]):
        result['status'] = 'Cancelled'
        result['detail'] = 'Payment failed — booking was not completed.'

    # Payment pending
    elif 'payment for this booking is incomplete' in text_lower or 'payment is incomplete' in text_lower:
        result['status'] = 'Payment Pending'
        result['detail'] = 'Payment incomplete — ticket not confirmed.'

    # Not found / Invalid
    elif 'booking not found' in text_lower:
        result['status'] = 'Not Found'
        result['detail'] = 'Booking not found on Air India. The PNR may have expired, been cancelled, or is a codeshare booking.'
    elif any(phrase in text_lower for phrase in [
        'pnr is not valid', 'invalid pnr', 'pnr not found',
    ]):
        result['status'] = 'Not Found'
        result['detail'] = 'PNR is not valid on Air India.'
    elif any(phrase in text_lower for phrase in [
        'booking cannot be found', 'no booking found', 'no record',
        'unable to fetch details', 'unable to verify your details',
    ]):
        result['status'] = 'Not Found'
        result['detail'] = 'Booking not found on Air India. Please check the PNR and last name.'

    # WAF blocks
    elif 'access denied' in text_lower or 'incapsula' in text_lower:
        result['status'] = 'Error'
        result['detail'] = 'Air India website blocked the request. Will retry later.'

    # ----- PROXIMITY-BASED STATUSES -----
    elif _keyword_near_pnr('cancelled', pnr, page_text, window=300) or ('cancelled' in text_lower and text_lower.count('cancelled') > 1):
        result['status'] = 'Cancelled'
        result['detail'] = extract_status_detail(page_text, 'cancelled')
    elif _keyword_near_pnr('rescheduled', pnr, page_text, window=300):
        result['status'] = 'Rescheduled'
        result['detail'] = extract_status_detail(page_text, 'rescheduled')
    elif _keyword_near_pnr('delayed', pnr, page_text, window=300):
        result['status'] = 'Delayed'
        result['detail'] = extract_status_detail(page_text, 'delayed')
    elif _keyword_near_pnr('confirmed', pnr, page_text, window=300):
        result['status'] = 'Confirmed'
        result['detail'] = extract_booking_detail(page_text)

    # Manage booking page with booking details (confirmed booking)
    elif ('manage your booking' in text_lower or 'your booking' in text_lower) and pnr.lower() in text_lower:
        result['status'] = 'Confirmed'
        result['detail'] = extract_booking_detail(page_text)

    # Generic confirmed keywords
    elif any(kw in text_lower for kw in [
        'confirmed', 'booked', 'itinerary', 'e-ticket',
        'seat selection', 'add-ons', 'check-in', 'checkin'
    ]):
        result['status'] = 'Confirmed'
        result['detail'] = extract_booking_detail(page_text)

    # Soft block — form re-displayed without any result
    elif 'search for a booking' in text_lower and 'continue' in text_lower:
        raise Exception("Air India soft-blocked the request (form re-displayed without result). Will retry.")

    # Form still showing — possibly soft block
    elif 'manage booking' in text_lower and 'booking reference' in text_lower and len(page_text) < 2000:
        raise Exception("Form still showing after submit — possible soft block")

    else:
        result['status'] = 'Checked'
        result['detail'] = page_text[:500] if page_text else 'Could not parse status'

    # Extract flight info for non-error statuses
    if result['status'] not in ('Not Found', 'Error', 'Cancelled', 'Check Failed'):
        try:
            result['flight_info'] = extract_flight_info_from_web(page_text, lastname)
        except Exception:
            pass

    return result


def _check_pnr_status_internal(pnr, lastname):
    """
    Check Air India PNR status with retries.
    Strategy: Try Playwright + persistent Chrome CDP first (best anti-bot),
    then fall back to undetected-chromedriver if Playwright is unavailable.
    """
    last_error = None
    
    # Strategy 1: Playwright + persistent Chrome CDP (best anti-bot)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _try_check_pnr_playwright(pnr, lastname, attempt)
        except ImportError as e:
            logger.warning(f"Playwright not available: {e}. Falling back to Selenium/UC.")
            break  # Don't retry import errors
        except Exception as e:
            last_error = e
            logger.warning(f"[AI-PW Attempt {attempt}/{MAX_RETRIES}] Failed: {e}")
            if attempt < MAX_RETRIES:
                wait_secs = random.randint(5, 15)
                logger.info(f"Waiting {wait_secs}s before Playwright retry...")
                time.sleep(wait_secs)

    # Strategy 2: Undetected-chromedriver (fallback)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _try_check_pnr(pnr, lastname, attempt)
        except Exception as e:
            last_error = e
            logger.warning(f"[AI-UC Attempt {attempt}/{MAX_RETRIES}] Failed: {e}")
            if attempt < MAX_RETRIES:
                err_str = str(e).lower()
                if any(k in err_str for k in ['target window', 'web view not found', 'form fill', 'form fields not filled', 'validation errors']):
                    wait_secs = random.randint(3, 8)
                    logger.info(f"Waiting {wait_secs}s before retry (Chrome crash / form failure)...")
                else:
                    wait_secs = attempt * 30 + random.randint(5, 15)
                    logger.info(f"Waiting {wait_secs}s before retry (longer backoff to avoid WAF)...")
                time.sleep(wait_secs)

    logger.error(f"All attempts failed for Air India PNR {pnr}: {last_error}")
    err_str = str(last_error).lower()
    if any(k in err_str for k in ['imperva', 'incapsula', 'access denied', 'blocked', 'waf', 'soft-block']):
        return {
            'status': 'Check Failed',
            'detail': "Air India website is temporarily blocking automated checks (WAF). Will retry on next scheduled run.",
            'raw_text': '',
        }
    return {
        'status': 'Error',
        'detail': f'Failed after all attempts. Last error: {str(last_error)}'
    }


def check_pnr_status(pnr, lastname):
    """
    Public entry point to check PNR status.
    Runs the scraper in a subprocess to isolate undetected_chromedriver from Flask threads,
    preventing 'target window already closed' and other threading crashes.
    """
    if _is_cloud():
        logger.warning(f"Air India scraping is disabled on Cloud/VPS due to strict Akamai IP blocks.")
        return {
            'status': 'Check Failed',
            'detail': 'Air India strictly blocks cloud server IPs. Status will be checked by the local app and synced automatically.',
            'raw_text': ''
        }

    import subprocess
    import json
    import os
    import sys
    
    script_path = os.path.abspath(__file__)
    try:
        logger.info(f"Launching subprocess for Air India PNR: {pnr}")
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        
        # Run this script directly with PNR and LASTNAME
        result = subprocess.run(
            [sys.executable, script_path, pnr, lastname],
            capture_output=True,
            text=True,
            env=env,
            timeout=180
        )
        
        if result.returncode != 0:
            logger.error(f"Subprocess failed with code {result.returncode}:\n{result.stderr}")
            return {'status': 'Error', 'detail': 'Scraper subprocess failed.'}
            
        # Parse output for JSON result
        for line in result.stdout.split('\n'):
            if line.startswith('JSON_RESULT:'):
                try:
                    return json.loads(line.replace('JSON_RESULT:', '').strip())
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse subprocess output: {e}")
                    
        logger.error(f"Could not find JSON_RESULT in subprocess output.\nStdout: {result.stdout}")
        return {'status': 'Error', 'detail': 'Invalid response from scraper.'}
        
    except subprocess.TimeoutExpired:
        logger.error(f"Subprocess timed out for Air India PNR: {pnr}")
        return {'status': 'Error', 'detail': 'Scraper timed out.'}
    except Exception as e:
        logger.error(f"Failed to launch subprocess: {e}")
        return {'status': 'Error', 'detail': str(e)}


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 3:
        pnr = sys.argv[1]
        lastname = sys.argv[2]
        
        # We must disable logging to stdout so it doesn't mess up JSON output, 
        # or we just ensure JSON_RESULT is on its own line and everything else is fine.
        result = _check_pnr_status_internal(pnr, lastname)
        
        # Print magic string for subprocess to parse
        import json
        print(f"\nJSON_RESULT:{json.dumps(result)}")
    else:
        print("Usage: python scraper_airindia.py <PNR> <LASTNAME>")
