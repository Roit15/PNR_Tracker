from selenium.webdriver.common.by import By
from scraper_airindia import _create_stealth_driver, _human_delay
import time

def test():
    driver = _create_stealth_driver()
    try:
        driver.get("https://www.airindia.com/in/en/manage/booking.html")
        time.sleep(10)
        pnr_input = driver.find_element(By.ID, "pnr-ip-id")
        lastname_input = driver.find_element(By.ID, "lastname-ip-id")
        
        # Focus and click
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", pnr_input)
        driver.execute_script("arguments[0].click();", pnr_input)
        
        # Send keys
        pnr_input.clear()
        pnr_input.send_keys("DN72VM")
        driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pnr_input)
        
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", lastname_input)
        driver.execute_script("arguments[0].click();", lastname_input)
        lastname_input.clear()
        lastname_input.send_keys("BANSAL")
        driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", lastname_input)
        
        time.sleep(2)
        
        # Read properties via JS
        pnr_val = driver.execute_script("return arguments[0].value;", pnr_input)
        last_val = driver.execute_script("return arguments[0].value;", lastname_input)
        
        print(f"PNR JS value: {pnr_val}")
        print(f"Last Name JS value: {last_val}")
        
        driver.save_screenshot("AI_test_filled.png")
        
        # Try to find if button is enabled
        btn = driver.find_element(By.XPATH, '//button[contains(text(), "Submit")]')
        print(f"Submit button enabled attribute: {btn.get_attribute('disabled')}")
        print(f"Submit button is_enabled(): {btn.is_enabled()}")
        
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(5)
        driver.save_screenshot("AI_test_after_submit.png")
        
    finally:
        driver.quit()

if __name__ == "__main__":
    test()
