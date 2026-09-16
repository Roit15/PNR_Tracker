import undetected_chromedriver as uc
import time

if __name__ == '__main__':
    try:
        options = uc.ChromeOptions()
        driver = uc.Chrome(options=options)
        driver.get('https://www.airindia.com/in/en/manage/manage-booking.html')
        time.sleep(5)
        print("Title:", driver.title)
        driver.save_screenshot('AI_test_uc.png')
        print("Success")
    except Exception as e:
        print("ERROR:", e)
    finally:
        try:
            driver.quit()
        except:
            pass
