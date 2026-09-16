from scraper import _create_stealth_driver
from selenium.webdriver.common.by import By
import time

driver = _create_stealth_driver()
driver.get("https://www.singaporeair.com/en_UK/sg/plan-travel/your-booking/managebooking/")
time.sleep(5)
try:
    pnr_input = driver.find_element(By.XPATH, '//input[@id="lasFamilyNameInputField"]/preceding::input[@type="text"][1]')
    lname_input = driver.find_element(By.ID, "lasFamilyNameInputField")
    print("Found PNR input:", pnr_input.get_attribute("outerHTML"))
    print("Found Last Name input:", lname_input.get_attribute("outerHTML"))
except Exception as e:
    print("Error:", e)
finally:
    driver.quit()
