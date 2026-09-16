import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from scraper_airindia import _create_stealth_driver, _dismiss_popups, _find_and_fill_form, AIRINDIA_HOME, AIRINDIA_URL, _human_delay

def main():
    pnr = "DN72VM"
    lastname = "BANSAL"
    
    driver = _create_stealth_driver()
    try:
        driver.delete_all_cookies()
        
        driver.get(AIRINDIA_HOME)
        _human_delay(4.0, 7.0)
        
        driver.get(AIRINDIA_URL)
        _human_delay(5.0, 9.0)
        
        wait = WebDriverWait(driver, 40)
        _dismiss_popups(driver, wait)
        _human_delay(0.5, 1.5)
        
        # WE WILL FILL IT MANUALLY TO SEE WHAT HAPPENS
        print("Filling form...")
        _find_and_fill_form(driver, wait, pnr, lastname)
        
        # Verify the actual value inside the input boxes!
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input:not([type])')
        visible_inputs = [inp for inp in inputs if inp.is_displayed()]
        for idx, inp in enumerate(visible_inputs):
            val = driver.execute_script("return arguments[0].value;", inp)
            print(f"Input {idx} value: '{val}'")
            
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
