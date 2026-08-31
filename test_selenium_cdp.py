import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import chrome_launcher
import time

logging.basicConfig(level=logging.INFO)

def test():
    chrome_launcher.ensure_chrome_running()
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9224")
    
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.goindigo.in/")
    time.sleep(3)
    print("Page title:", driver.title)
    driver.quit() # wait, quit might close the browser, which we don't want! We should just close the tab.

test()
