from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from scraper import fetch_indigo_status, extract_flight_info_from_web

options = Options()
options.add_argument('--headless')
driver = webdriver.Chrome(options=options)

try:
    result = fetch_indigo_status(driver, "N4T3PY", "Samantara")
    print(result)
finally:
    driver.quit()
