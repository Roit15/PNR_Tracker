from scraper_airindia import _create_stealth_driver, _dismiss_popups, By, time

def test():
    driver = _create_stealth_driver()
    driver.get("https://www.airindia.com/in/en/manage/booking.html")
    time.sleep(10)
    
    _dismiss_popups(driver, None)
    
    pnr = "DN72VM"
    lastname = "BANSAL"
    
    script = """
    const pnrInput = document.querySelector('input[placeholder*="PNR"], input[id*="pnr"], input[name*="pnr"], input[formcontrolname="bookingReference"]');
    const nameInput = document.querySelector('input[placeholder*="Last"], input[id*="last"], input[name*="last"], input[formcontrolname="lastName"]');
    
    if (pnrInput && nameInput) {
        let setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        
        setter.call(pnrInput, arguments[0]);
        pnrInput.dispatchEvent(new Event('input', {bubbles: true}));
        
        setter.call(nameInput, arguments[1]);
        nameInput.dispatchEvent(new Event('input', {bubbles: true}));
        
        const btn = document.querySelector('button[type="submit"], button.submit, .submit-btn');
        if (btn) btn.click();
        return "Success";
    }
    return "Inputs not found";
    """
    
    res = driver.execute_script(script, pnr, lastname)
    print("JS form fill result:", res)
    
    time.sleep(15)
    print("CURRENT URL:", driver.current_url)
    try:
        body = driver.find_element(By.TAG_NAME, 'body').text
        print(body[:2000])
        driver.save_screenshot("scratch/test_ai.png")
    except Exception as e:
        print("Could not get body text:", e)
    
    driver.quit()
    
test()
