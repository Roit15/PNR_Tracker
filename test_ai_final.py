import time
from scraper_airindia import _create_stealth_driver, _dismiss_popups, By, _find_and_fill_form, AIRINDIA_URL
from selenium.webdriver.support.ui import WebDriverWait

if __name__ == '__main__':
    driver = _create_stealth_driver()
    try:
        print("Going to manage booking directly...")
        driver.get(AIRINDIA_URL)
        time.sleep(5)
        wait = WebDriverWait(driver, 10)
        _dismiss_popups(driver, wait)
        time.sleep(2)

        _find_and_fill_form(driver, wait, 'DN72VM', 'BANSAL')
        print("Form filled and submitted!")

        time.sleep(10)
        html = driver.execute_script("return document.body.innerHTML;")
        with open('body.html', 'w') as fh:
            fh.write(html)
        driver.save_screenshot('AI_test_result.png')
        print("Screenshot saved to AI_test_result.png")
    except Exception as e:
        print("ERROR:", e)
    finally:
        driver.quit()
