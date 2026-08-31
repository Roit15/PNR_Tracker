import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import chrome_launcher

logging.basicConfig(level=logging.INFO)

def test():
    chrome_launcher.ensure_chrome_running()
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9224")
    
    driver = webdriver.Chrome(options=options)
    driver.save_screenshot("test_cdp_screenshot.png")
    print("Screenshot saved to test_cdp_screenshot.png")
    
    # Let's see what tabs are open
    print("Window handles:", driver.window_handles)
    
test()
