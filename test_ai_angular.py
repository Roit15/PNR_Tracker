import time
from scraper_airindia import _create_stealth_driver, _dismiss_popups, By, AIRINDIA_URL
from selenium.webdriver.support.ui import WebDriverWait

if __name__ == '__main__':
    driver = _create_stealth_driver()
    try:
        driver.get(AIRINDIA_URL)
        time.sleep(5)
        wait = WebDriverWait(driver, 10)
        _dismiss_popups(driver, wait)
        
        # Inject script to see if form is valid
        js = """
        const pnrInput = document.querySelector('input[id*="pnr"], input[formcontrolname*="pnr"]');
        const lastNameInput = document.querySelector('input[id*="last"], input[formcontrolname*="lastName"]');
        
        if (pnrInput) {
            pnrInput.value = 'DN72VM';
            pnrInput.dispatchEvent(new Event('input', { bubbles: true }));
            pnrInput.dispatchEvent(new Event('change', { bubbles: true }));
            pnrInput.dispatchEvent(new Event('blur', { bubbles: true }));
        }
        
        if (lastNameInput) {
            lastNameInput.value = 'BANSAL';
            lastNameInput.dispatchEvent(new Event('input', { bubbles: true }));
            lastNameInput.dispatchEvent(new Event('change', { bubbles: true }));
            lastNameInput.dispatchEvent(new Event('blur', { bubbles: true }));
        }
        
        const submitBtn = document.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.click();
        }
        """
        driver.execute_script(js)
        print("JS form fill and submit executed.")
        time.sleep(5)
        
        html = driver.execute_script("return document.body.innerHTML;")
        if "Booking Not Found" in html:
            print("UI still says: Booking Not Found")
        else:
            print("Success? Let's check keywords.")
            if "Select flight" in html or "itinerary" in html.lower():
                print("Booking found!!")
                
        driver.save_screenshot('AI_test_angular.png')
        
    except Exception as e:
        print("ERROR:", e)
    finally:
        driver.quit()
