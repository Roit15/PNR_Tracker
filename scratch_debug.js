const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());
(async () => {
    const browser = await puppeteer.launch({
      headless: false,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1920,1080', '--window-position=-2400,-2400'],
      defaultViewport: { width: 1920, height: 1080 }
    });
    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36');
    await page.goto('https://www.srilankan.com/en_uk/plan-and-book/manage-your-booking', {waitUntil: 'networkidle2'});
    await new Promise(r => setTimeout(r, 5000));
    
    // Check what btnMybSearch is
    const btnHtml = await page.evaluate(() => {
        const btn = document.querySelector('#btnMybSearch');
        return btn ? btn.outerHTML : 'NOT FOUND';
    });
    console.log('Button HTML: ' + btnHtml);

    // Fill the form
    await page.type('#lastname2refx', 'VANIGOTTA', { delay: 100 });
    await page.type('#bookref2refx', '9GRW4B', { delay: 100 });
    
    // Submit
    const submitBtn = await page.$('#btnMybSearch');
    await submitBtn.evaluate(b => b.click());
    
    await new Promise(r => setTimeout(r, 10000));
    
    const pages = await browser.pages();
    console.log('Number of pages: ' + pages.length);
    for (let i=0; i<pages.length; i++) {
        console.log('Page ' + i + ' URL: ' + pages[i].url());
        const text = await pages[i].evaluate(() => document.body ? document.body.innerText.substring(0, 200) : 'NO BODY');
        console.log('Page ' + i + ' text: ' + text.replace(/\n/g, ' '));
        await pages[i].screenshot({path: 'screenshots/page_' + i + '.png'});
    }
    
    await browser.close();
})();
