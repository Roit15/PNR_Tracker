import undetected_chromedriver as uc
import time
from selenium.webdriver.support.ui import WebDriverWait

if __name__ == '__main__':
    try:
        options = uc.ChromeOptions()
        # options.add_argument('--window-size=1920,1080')
        
        driver = uc.Chrome(options=options)
        print("Driver started")
        
        url = "https://www.airindia.com/in/en/manage/booking.html"
        print(f"Loading {url}...")
        driver.get(url)
        
        time.sleep(10)
        
        print("Title:", driver.title)
        driver.save_screenshot('AI_test_uc2.png')
        print("Screenshot saved to AI_test_uc2.png")
    except Exception as e:
        print("ERROR:", e)
    finally:
        try:
            driver.quit()
        except:
            pass
