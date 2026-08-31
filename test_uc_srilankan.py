import ssl
import time

ssl._create_default_https_context = ssl._create_unverified_context

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def test_uc():
    options = uc.ChromeOptions()
    options.headless = False
    
    # Use version_main=151 to match the installed Chrome
    driver = uc.Chrome(options=options, version_main=151)
    
    try:
        url = "https://www.srilankan.com/en_uk/plan-and-book/manage-your-booking"
        print(f"Loading {url}...")
        driver.get(url)
        time.sleep(5)
        
        # Submit the form
        wait = WebDriverWait(driver, 10)
        lastname = wait.until(EC.presence_of_element_located((By.ID, "lastname2refx")))
        lastname.send_keys("Vanigotta")
        
        pnr = driver.find_element(By.ID, "bookref2refx")
        pnr.send_keys("9GRW4B")
        
        btn = driver.find_element(By.ID, "btnMybSearch")
        driver.execute_script("arguments[0].click();", btn)
        
        print("Clicked submit, waiting for results...")
        time.sleep(15)
        
        print("After submit, URL:", driver.current_url)
        page_source = driver.page_source
        if "Incapsula" in page_source or "Incident ID:" in page_source:
            print("❌ Blocked by Imperva WAF on result page")
        elif "Khushi" in page_source or "Vanigotta" in page_source:
            print("✅ Found booking details!")
        else:
            print("❓ Unknown status")
            print(page_source[:500])
        
    finally:
        driver.quit()

if __name__ == '__main__':
    test_uc()
