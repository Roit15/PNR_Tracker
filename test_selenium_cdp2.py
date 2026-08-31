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
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.goindigo.in/")
    time.sleep(2)
    driver.quit()
    
    time.sleep(2)
    print("Port open after quit():", is_port_in_use(9224))

test()
