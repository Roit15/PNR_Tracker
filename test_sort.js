const playwright = require('playwright');
(async () => {
    const browser = await playwright.chromium.launch();
    const page = await browser.newPage();
    page.on('console', msg => console.log('BROWSER CONSOLE:', msg.text()));
    page.on('pageerror', error => console.log('BROWSER ERROR:', error.message));
    
    await page.goto('http://127.0.0.1:5001'); // Assuming app runs on 5001 or 5000
    
    const pnrHeader = await page.locator('th.sortable').first();
    await pnrHeader.click();
    console.log("Clicked PNR header");
    
    await page.waitForTimeout(1000);
    await browser.close();
})();
