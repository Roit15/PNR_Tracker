import sys
import time
import os
from scraper_airindia import _create_stealth_driver, AIRINDIA_HOME, AIRINDIA_URL, _dismiss_popups
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

def main():
    driver = _create_stealth_driver()
    try:
        print("Warming up homepage...")
        driver.get(AIRINDIA_HOME)
        time.sleep(5)
        
        print("Navigating to manage booking...")
        driver.get(AIRINDIA_URL)
        time.sleep(10)
        
        wait = WebDriverWait(driver, 20)
        _dismiss_popups(driver, wait)
        
        inputs = driver.find_elements(By.TAG_NAME, "input")
        print(f"Found {len(inputs)} inputs on the page:")
        for idx, inp in enumerate(inputs):
            try:
                print(f"Input {idx}: id='{inp.get_attribute('id')}' type='{inp.get_attribute('type')}' name='{inp.get_attribute('name')}' placeholder='{inp.get_attribute('placeholder')}' class='{inp.get_attribute('class')}' aria-label='{inp.get_attribute('aria-label')}' displayed={inp.is_displayed()}")
            except Exception as e:
                print(f"Input {idx}: error {e}")
                
        buttons = driver.find_elements(By.TAG_NAME, "button")
        print(f"Found {len(buttons)} buttons on the page:")
        for idx, btn in enumerate(buttons):
            try:
                print(f"Button {idx}: text='{btn.text}' type='{btn.get_attribute('type')}' id='{btn.get_attribute('id')}' class='{btn.get_attribute('class')}' displayed={btn.is_displayed()}")
            except Exception as e:
                pass

        html = driver.page_source
        with open("ai_manage_booking.html", "w") as f:
            f.write(html)
        print("Saved HTML to ai_manage_booking.html")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
