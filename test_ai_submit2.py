import sys
import time
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from scraper_airindia import _create_stealth_driver, _dismiss_popups, _find_and_fill_form, AIRINDIA_HOME, AIRINDIA_URL, _human_delay

def main():
    pnr = "DN72VM"
    lastname = "BANSAL"
    
    driver = _create_stealth_driver()
    try:
        driver.delete_all_cookies() # Try deleting cookies
        
        driver.get(AIRINDIA_HOME)
        _human_delay(4.0, 7.0)
        
        # screenshot home
        driver.save_screenshot("AI_test_home.png")
        
        driver.get(AIRINDIA_URL)
        _human_delay(5.0, 9.0)
        
        # screenshot before popups
        driver.save_screenshot("AI_test_manage.png")
        
        wait = WebDriverWait(driver, 40)
        _dismiss_popups(driver, wait)
        _human_delay(0.5, 1.5)
        
        print("Filling form...")
        _find_and_fill_form(driver, wait, pnr, lastname)
        print("Form filled and submitted. Waiting 10 seconds...")
        time.sleep(10)
        
        driver.save_screenshot("AI_test_after_submit.png")
        with open("debug_ai_test_after_submit.html", "w") as f:
            f.write(driver.page_source)
        print("Saved AI_test_after_submit.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
