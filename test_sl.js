const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('https://www.srilankan.com/en_uk/plan-and-book/manage-booking');
  const lnPlaceholder = await page.getAttribute('#lastname2refx', 'placeholder').catch(()=>null);
  const pnrPlaceholder = await page.getAttribute('#bookref2refx', 'placeholder').catch(()=>null);
  console.log("lastname2refx:", lnPlaceholder);
  console.log("bookref2refx:", pnrPlaceholder);
  await browser.close();
})();
