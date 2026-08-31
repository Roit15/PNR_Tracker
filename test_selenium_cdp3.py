import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import chrome_launcher
import time
import socket

logging.basicConfig(level=logging.INFO)

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def test():
    chrome_launcher.ensure_chrome_running()
    print("Port open before:", is_port_in_use(9224))
    
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9224")
    driver1 = webdriver.Chrome(options=options)
    driver1.get("https://www.goindigo.in/")
    time.sleep(1)
    
    # Do we need to explicitly create a new window if we want isolation?
    # webdriver.Chrome(options=options) attaches to the currently active tab if one exists, 
    # which is bad if multiple scripts run, but we will run them sequentially.
    driver1.quit()
    
    time.sleep(2)
    print("Port open after quit 1:", is_port_in_use(9224))

    # Second driver
    driver2 = webdriver.Chrome(options=options)
    driver2.get("https://www.google.com/")
    time.sleep(1)
    driver2.quit()
    
    time.sleep(2)
    print("Port open after quit 2:", is_port_in_use(9224))

test()
