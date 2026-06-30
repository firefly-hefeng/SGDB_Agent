/** Take a true full-page screenshot of the landing page by scrolling first. */
import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  const errors = [];
  page.on('pageerror', (e) => errors.push(`PAGEERROR ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('http://localhost:5173/singledb/', { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('load').catch(() => {});
  await page.waitForTimeout(3000); // wait for featured collections fetch

  // Slow auto-scroll to trigger lazy / progressive rendering
  await page.evaluate(async () => {
    await new Promise((resolve) => {
      let total = 0;
      const distance = 200;
      const timer = setInterval(() => {
        window.scrollBy(0, distance);
        total += distance;
        if (total >= document.body.scrollHeight) {
          clearInterval(timer);
          resolve();
        }
      }, 80);
    });
  });
  await page.waitForTimeout(800);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(400);

  // Page uses `flex-1 overflow-y-auto` so the scrollable element is INSIDE the
  // app shell, not the body. Find the inner scroll container's real height.
  const innerH = await page.evaluate(() => {
    const scrollable = Array.from(document.querySelectorAll('*')).find((el) => {
      const cs = window.getComputedStyle(el);
      return (cs.overflowY === 'auto' || cs.overflowY === 'scroll') && el.scrollHeight > el.clientHeight;
    });
    return scrollable ? scrollable.scrollHeight : document.body.scrollHeight;
  });
  console.log('inner scroll height:', innerH);
  await page.setViewportSize({ width: 1440, height: Math.min(innerH + 100, 8000) });
  await page.waitForTimeout(800);
  await page.screenshot({ path: '/tmp/walkthrough/landing-full.png', fullPage: false });
  console.log('errors:', errors.length, errors.slice(0, 3));
  console.log('h1:', await page.locator('h1').first().textContent());
  const collectionCount = await page.locator('text=Featured collections').count();
  console.log('Featured collections section found:', collectionCount);

  await browser.close();
})();
