import time
from scraper import _create_stealth_driver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = _create_stealth_driver()
driver.get("https://www.goindigo.in/account/my-bookings.html")
time.sleep(10)
wait = WebDriverWait(driver, 40)
pnr_input = wait.until(EC.visibility_of_element_located((By.NAME, 'pnr-booking-ref')))
pnr_input.click()
pnr_input.send_keys("R4M6Z9")
time.sleep(1)
email_input = driver.find_element(By.NAME, 'email-last-name')
email_input.click()
email_input.send_keys("JANGRA")
time.sleep(1)
email_input.send_keys(Keys.RETURN)
time.sleep(15)
text = driver.find_element(By.TAG_NAME, 'body').text
with open("indigo_success_dump.txt", "w") as f:
    f.write(text)
driver.quit()
print("Dumped to indigo_success_dump.txt")
