import logging
import random
from scraper_airindia import _create_stealth_driver, _find_and_fill_form
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
import time

logging.basicConfig(level=logging.INFO)

def main():
    driver = _create_stealth_driver()
    try:
        driver.get("https://www.airindia.com/in/en/manage/booking.html")
        wait = WebDriverWait(driver, 15)
        time.sleep(5)
        
        pnr = "AH2NWZ"
        lastname = "Garg"
        
        pnr_input, lastname_input = _find_and_fill_form(driver, wait, pnr, lastname)
        
        if pnr_input and lastname_input:
            pnr_class = pnr_input.get_attribute('class')
            last_class = lastname_input.get_attribute('class')
            print(f"PNR Class: {pnr_class}")
            print(f"LastName Class: {last_class}")
            
            # Check for error elements
            errors = driver.find_elements(By.CSS_SELECTOR, "mat-error")
            for e in errors:
                print(f"Error: {e.text}")
                
            print("Form filled. Now clicking submit manually to see what happens...")
            submit_btn = driver.find_element(By.XPATH, '//button[contains(text(), "Submit")]')
            driver.execute_script("arguments[0].click();", submit_btn)
            
            time.sleep(10)
            print("Result page text:")
            print(driver.find_element(By.TAG_NAME, "body").text[:500])
        else:
            print("Could not fill form.")
            
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
