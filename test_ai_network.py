import sys
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from scraper_airindia import _dismiss_popups, _find_and_fill_form, AIRINDIA_HOME, AIRINDIA_URL, _human_delay
import undetected_chromedriver as uc

def main():
    pnr = "DN72VM"
    lastname = "BANSAL"
    
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1280,1024")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    driver = uc.Chrome(options=options, headless=True)
    try:
        driver.delete_all_cookies()
        
        driver.get(AIRINDIA_HOME)
        _human_delay(4.0, 7.0)
        
        driver.get(AIRINDIA_URL)
        _human_delay(5.0, 9.0)
        
        wait = WebDriverWait(driver, 40)
        _dismiss_popups(driver, wait)
        _human_delay(0.5, 1.5)
        
        print("Filling form...")
        _find_and_fill_form(driver, wait, pnr, lastname)
        print("Form filled and submitted. Waiting 10 seconds...")
        time.sleep(10)
        
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                log_json = json.loads(entry["message"])["message"]
                if log_json["method"] == "Network.responseReceived":
                    resp = log_json["params"]["response"]
                    url = resp["url"]
                    status = resp["status"]
                    if "api" in url.lower() or "booking" in url.lower() or "manage" in url.lower():
                        print(f"URL: {url}, Status: {status}")
            except Exception:
                pass
                
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
