import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import chrome_launcher
import time

logging.basicConfig(level=logging.INFO)

def test():
    chrome_launcher.ensure_chrome_running()
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9224")
    
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.goindigo.in/")
    
    wait = WebDriverWait(driver, 15)
    pnr_input = wait.until(
        EC.visibility_of_element_located((By.NAME, 'pnr-booking-ref'))
    )
    pnr_input.clear()
    pnr_input.send_keys("Z9MVVC")
    time.sleep(0.5)
    
    email_input = driver.find_element(By.NAME, 'email-last-name')
    email_input.clear()
    email_input.send_keys("Kansal")
    time.sleep(1)
    
    get_started = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[title="Get Started"]'))
    )
    time.sleep(0.5)
    driver.execute_script("arguments[0].click();", get_started)
    
    print("Clicked. Waiting for results...")
    for i in range(20):
        time.sleep(1)
        text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        print(f"[{i}] URL: {driver.current_url}")
        if 'terminal information' in text or 'invalid' in text or 'not found' in text:
            print("Found result text!")
            break
            
test()
