from scraper import _create_stealth_driver
from selenium.webdriver.common.by import By
import time

driver = _create_stealth_driver()
driver.get("https://www.singaporeair.com/en_UK/sg/plan-travel/your-booking/managebooking/")
time.sleep(5)
inputs = driver.find_elements(By.TAG_NAME, "input")
for i in inputs:
    print(i.get_attribute('id'), i.get_attribute('name'), i.get_attribute('type'), i.get_attribute('placeholder'))
driver.quit()
