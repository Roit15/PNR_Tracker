const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const pnr = process.argv[2];
const lastname = process.argv[3];

if (!pnr || !lastname) {
  process.stdout.write("RESULT_ERROR: Missing PNR or lastname arguments\n");
  process.exit(0);
}

(async () => {
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: 'new',
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--window-size=1920,1080',
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage'
      ],
      defaultViewport: { width: 1920, height: 1080 }
    });

    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36');

    // Strategy: The SriLankan manage-booking SPA lives at digital.srilankan.com.
    // The /booking/api/manage-booking/retrieve path bypasses Imperva WAF on POST.
    // We warm up cookies by visiting /booking first, then POST the form.

    // Step 1: Warm up digital.srilankan.com to get Incapsula cookies
    console.log("Warming up digital.srilankan.com...");
    try {
      await page.goto('https://digital.srilankan.com/booking', {
        waitUntil: 'networkidle2',
        timeout: 30000
      });
      await new Promise(r => setTimeout(r, 5000));
    } catch (e) {
      console.log("Warmup issue: " + e.message);
    }

    // Step 2: POST to the API path that bypasses WAF
    console.log("Submitting booking retrieval...");
    await page.evaluate((recLoc, lastName) => {
      const form = document.createElement('form');
      form.method = 'post';
      form.action = '/booking/api/manage-booking/retrieve';
      
      const i1 = document.createElement('input');
      i1.type = 'hidden';
      i1.name = 'recLoc';
      i1.value = recLoc;
      form.appendChild(i1);
      
      const i2 = document.createElement('input');
      i2.type = 'hidden';
      i2.name = 'lastName';
      i2.value = lastName;
      form.appendChild(i2);
      
      document.body.appendChild(form);
      form.submit();
    }, pnr, lastname);

    // Wait for SPA navigation
    try {
      await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 30000 });
    } catch (e) {}

    // Wait for the Angular SPA to render — poll until content appears
    console.log("Waiting for SPA to render...");
    let bodyText = '';
    for (let i = 0; i < 12; i++) {
      await new Promise(r => setTimeout(r, 5000));
      bodyText = await page.evaluate(() => document.body ? document.body.innerText : '');
      
      if (bodyText.length > 200 && !bodyText.includes('Please stand by') && !bodyText.includes('getting everything ready')) {
        console.log("SPA rendered (" + bodyText.length + " chars)");
        break;
      }
      
      // Also check if content is in an iframe
      if (bodyText.length < 50) {
        const frames = page.frames();
        for (const frame of frames) {
          try {
            const frameText = await frame.evaluate(() => document.body ? document.body.innerText : '');
            if (frameText.length > bodyText.length) {
              bodyText = frameText;
            }
          } catch(e) {}
        }
        if (bodyText.length > 200) {
          console.log("SPA rendered in iframe (" + bodyText.length + " chars)");
          break;
        }
      }
    }

    // Take screenshot
    await page.screenshot({ path: 'screenshots/node_result.png', fullPage: true });
    console.log("Screenshot saved");
    await browser.close();

    // Classify result
    if (!bodyText || bodyText.length < 50) {
      process.stdout.write("RESULT_ERROR: SPA did not render (Imperva challenge may have failed)\n");
    } else if (bodyText.includes("Incident ID") || bodyText.includes("Access denied")) {
      process.stdout.write("RESULT_ERROR: Blocked by WAF after form submission\n");
    } else if (bodyText.includes("something went wrong")) {
      // This is the SPA's error recovery page — PNR not found or expired
      process.stdout.write("RESULT_NOT_FOUND: Booking could not be retrieved — PNR may be expired or invalid\n");
    } else if (
      bodyText.includes("Confirmed") ||
      bodyText.includes("Your flight") ||
      bodyText.includes("One way") ||
      bodyText.includes("Economy") ||
      bodyText.includes("Business") ||
      bodyText.includes("nonstop") ||
      bodyText.includes("UL ") ||
      bodyText.includes("Departure") ||
      bodyText.includes("services summary") ||
      bodyText.includes("itinerary") ||
      bodyText.includes("passenger")
    ) {
      process.stdout.write("RESULT_SUCCESS: " + bodyText.substring(0, 8000) + "\n");
    } else {
      process.stdout.write("RESULT_UNKNOWN: " + bodyText.substring(0, 3000) + "\n");
    }

  } catch (err) {
    if (browser) {
      try { await browser.close(); } catch(e) {}
    }
    process.stdout.write("RESULT_ERROR: " + err.toString() + "\n");
  }
})();
