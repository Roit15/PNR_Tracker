import time
import os

from scraper import _create_stealth_driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def test_sa():
    driver = _create_stealth_driver()
    try:
        print("Navigating to SA...")
        driver.get('https://www.singaporeair.com/en_UK/sg/plan-travel/your-booking/managebooking/')
        
        wait = WebDriverWait(driver, 20)
        
        # Accept cookies if the button is there
        try:
            accept_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]")))
            accept_btn.click()
            print("Accepted cookies.")
            time.sleep(1)
        except Exception as e:
            print("No accept cookies button found or failed to click.")

        # The first text input is PNR, the second is Last Name (has id lasFamilyNameInputField)
        text_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
        pnr_input = text_inputs[0]
        lname_input = driver.find_element(By.ID, "lasFamilyNameInputField")
        
        pnr_input.clear()
        pnr_input.send_keys("BISXAN")
        
        lname_input.clear()
        lname_input.send_keys("Sharma")
        
        # Click the manage booking submit button
        # Might be a button with text 'Manage booking' inside the form
        submit_btn = driver.find_element(By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'manage booking')]")
        submit_btn.click()
        
        print("Submitted form. Waiting for results...")
        time.sleep(20)
        
        print("Results page:")
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        print(body_text[:1000])
        
        driver.save_screenshot('sa_results.png')
        with open('sa_results.txt', 'w') as f:
            f.write(body_text)
            
    finally:
        driver.quit()

if __name__ == '__main__':
    test_sa()
