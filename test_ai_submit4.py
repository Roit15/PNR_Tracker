import time
from scraper_airindia import _create_stealth_driver, _dismiss_popups, _find_and_fill_form, AIRINDIA_HOME, AIRINDIA_URL, _human_delay
from selenium.webdriver.support.ui import WebDriverWait

def main():
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
        
        _find_and_fill_form(driver, wait, "DN72VM", "BANSAL")
        time.sleep(2)
        driver.save_screenshot("AI_test_filled.png")
        print("Saved AI_test_filled.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
