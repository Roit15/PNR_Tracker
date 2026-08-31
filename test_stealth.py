import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium_stealth import stealth
from selenium.webdriver.common.by import By

def test_stealth():
    options = Options()
    options.add_argument("start-maximized")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
        
    stealth(driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    
    try:
        print("Pre-loading digital.srilankan.com to solve Incapsula...")
        driver.get("https://digital.srilankan.com/")
        time.sleep(8)
        
        url = "https://www.srilankan.com/en_uk/plan-and-book/manage-your-booking"
        print(f"Loading {url}...")
        driver.get(url)
        time.sleep(8)
        
        try:
            btns = driver.find_elements(By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]")
            for btn in btns:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1)
        except Exception:
            pass
            
        driver.find_element(By.ID, "lastname2refx").send_keys("Vanigotta")
        driver.find_element(By.ID, "bookref2refx").send_keys("9GRW4B")
        
        btn = driver.find_element(By.ID, "btnMybSearch")
        driver.execute_script("arguments[0].click();", btn)
        print("Clicked submit!")
        
        time.sleep(15)
        
        page_source = driver.page_source
        print("Final URL:", driver.current_url)
        if "Incident ID:" in page_source or "Access denied" in page_source:
            print("❌ Blocked by Imperva WAF on submit")
        elif "manage-your-booking" in driver.current_url:
            print("❓ Still on manage booking page")
        else:
            print("✅ Successfully got past the submit!")
            if "Khushi" in page_source or "Vanigotta" in page_source:
                print("✅ Found booking details!")
    finally:
        driver.quit()

if __name__ == '__main__':
    test_stealth()
