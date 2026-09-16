import time
import json
from scraper_airindia import _create_stealth_driver, _dismiss_popups, By, _find_and_fill_form, AIRINDIA_URL
from selenium.webdriver.support.ui import WebDriverWait

if __name__ == '__main__':
    driver = _create_stealth_driver()
    try:
        driver.get(AIRINDIA_URL)
        time.sleep(5)
        wait = WebDriverWait(driver, 10)
        _dismiss_popups(driver, wait)
        
        # Inject fetch interceptor
        driver.execute_script("""
            window.interceptedRequests = [];
            const originalFetch = window.fetch;
            window.fetch = async function(...args) {
                let url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : 'unknown');
                if (url.includes('manage-booking') || url.includes('pnr')) {
                    let body = '';
                    if (args[1] && args[1].body) body = args[1].body;
                    window.interceptedRequests.push({url: url, body: body});
                }
                return originalFetch.apply(this, args);
            };
            const originalXHR = window.XMLHttpRequest.prototype.open;
            window.XMLHttpRequest.prototype.open = function(method, url) {
                this.addEventListener('load', function() {
                    if (url.includes('manage-booking') || url.includes('pnr') || url.includes('api')) {
                        window.interceptedRequests.push({url: url, status: this.status, response: this.responseText});
                    }
                });
                return originalXHR.apply(this, arguments);
            };
        """)
        
        _find_and_fill_form(driver, wait, 'DN72VM', 'BANSAL')
        print("Form filled and submitted!")
        time.sleep(8)
        
        requests = driver.execute_script("return window.interceptedRequests;")
        print("Intercepted Requests:")
        print(json.dumps(requests, indent=2))
        
        html = driver.execute_script("return document.body.innerHTML;")
        if "Booking Not Found" in html:
            print("UI says: Booking Not Found")
        
    except Exception as e:
        print("ERROR:", e)
    finally:
        driver.quit()
