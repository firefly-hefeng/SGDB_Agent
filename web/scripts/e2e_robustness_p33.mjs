// Phase 33 — frontend robustness: condition-chip removal round-trip,
// honest-zero empty state, and a mobile viewport render.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.env.E2E_BASE || 'http://localhost:8000/singledb';
const OUT = '/tmp/p33_shots';
mkdirSync(OUT, { recursive: true });
let failures = 0;
const check = (c, m) => { console.log(`[rb] ${c ? 'PASS' : 'FAIL'} — ${m}`); if (!c) failures++; };

const browser = await chromium.launch();
try {
  // ── 1. Chip removal round-trip ──
  {
    const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
    const errs = []; page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' });
    await page.getByRole('textbox', { name: /natural-language search/i }).fill('pediatric brain samples');
    await page.getByRole('button', { name: /^Search/i }).click();
    await page.locator('table tbody tr').first().waitFor({ state: 'attached', timeout: 60000 });
    const before = await page.locator('table tbody tr').count();
    // ConditionCards render a remove (×) per chip; remove the first chip.
    const removeBtns = page.getByRole('button', { name: /remove/i });
    const nRemove = await removeBtns.count();
    check(nRemove > 0, `condition chips have remove buttons (${nRemove})`);
    if (nRemove > 0) {
      await removeBtns.first().click();
      await page.waitForTimeout(1500);
      const after = await page.locator('table tbody tr').count();
      check(after > 0, `re-searched after chip removal (${before}→${after} rows, no crash)`);
    }
    check(errs.filter(t => !/favicon|404|net::ERR/i.test(t)).length === 0, 'no console errors (chip removal)');
    await page.close();
  }

  // ── 2. Honest-zero empty state ──
  {
    const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
    await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' });
    await page.getByRole('textbox', { name: /natural-language search/i }).fill('zebrafish brain atlas');
    await page.getByRole('button', { name: /^Search/i }).click();
    await page.waitForTimeout(8000); // let the agent resolve to 0
    const body = await page.locator('body').innerText();
    const rows = await page.locator('table tbody tr').count();
    // Either an explicit empty state or simply no data rows — but NOT a crash.
    check(!/We couldn't find that page|TypeError|undefined is not/i.test(body), 'zero-result page did not crash');
    check(rows === 0 || /no (results|matches|samples|datasets)|0 samples|try|discover|broaden/i.test(body),
      `honest-zero shows an empty state (rows=${rows})`);
    await page.screenshot({ path: `${OUT}/rb_zero.png` });
    await page.close();
  }

  // ── 3. Mobile viewport render ──
  {
    const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true })).newPage();
    const errs = []; page.on('pageerror', e => errs.push(String(e)));
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientW = await page.evaluate(() => document.documentElement.clientWidth);
    check(scrollW <= clientW + 8, `no horizontal overflow on mobile landing (scroll ${scrollW} vs client ${clientW})`);
    await page.goto(`${BASE}/explore`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const body = await page.locator('body').innerText();
    check(body.length > 100, 'explore renders content on mobile');
    check(errs.length === 0, `no page errors on mobile (${errs.length})`);
    await page.screenshot({ path: `${OUT}/rb_mobile.png`, fullPage: true });
    await page.close();
  }
} catch (e) {
  console.log('[rb] EXCEPTION', e.message); failures++;
} finally {
  await browser.close();
  console.log(`[rb] DONE — ${failures} failure(s)`);
  process.exit(failures ? 1 : 0);
}
