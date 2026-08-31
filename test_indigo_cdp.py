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
    
    try:
        pnr_input = WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.NAME, 'pnr-booking-ref'))
        )
        print("Found pnr input!")
    except Exception as e:
        print("Failed to find pnr input:", e)
        driver.save_screenshot("indigo_fail.png")
        print("Saved indigo_fail.png")
    
test()
