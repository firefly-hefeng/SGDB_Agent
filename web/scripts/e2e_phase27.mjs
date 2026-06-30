// Phase 27 E2E — drives the real Advanced Search UI against the running
// backend (vite dev :5173 → proxy → :8000). Verifies: results render, the
// ExecutionTrace panel shows stages + final SQL, and search state survives
// navigating away and back (Issue 1). Captures console/page errors.
//
// Usage: node scripts/e2e_phase27.mjs
import { chromium } from 'playwright';

const BASE = process.env.E2E_BASE || 'http://localhost:5173/singledb';
const OUT = '/tmp/p27_shots';
import { mkdirSync } from 'node:fs';
mkdirSync(OUT, { recursive: true });

const log = (...a) => console.log('[e2e]', ...a);
let failures = 0;
const check = (cond, msg) => { log(`${cond ? 'PASS' : 'FAIL'} — ${msg}`); if (!cond) failures++; };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();

const consoleErrors = [];
const pageErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => pageErrors.push(String(e)));

try {
  // ── 1. Advanced search: submit NL query ──
  log('navigate to /search');
  await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' });
  await page.screenshot({ path: `${OUT}/01_search_empty.png` });

  const input = page.getByRole('textbox', { name: /natural-language search/i });
  await input.fill('human lung healthy 10x');
  await page.getByRole('button', { name: /^Search/i }).click();
  log('submitted query; waiting for results…');

  // Wait for the results table to have data rows (up to 90s for the agent).
  await page.locator('table tbody tr').first().waitFor({ state: 'attached', timeout: 90000 });
  await page.screenshot({ path: `${OUT}/02_search_results.png`, fullPage: true });

  const rowCount = await page.locator('table tbody tr').count();
  check(rowCount > 0, `results table has ${rowCount} rows`);

  // Condition chips reflect the parse
  const bodyText = await page.locator('body').innerText();
  check(/lung/i.test(bodyText), 'page mentions parsed "lung"');

  // ── 2. ExecutionTrace panel: stages + SQL ──
  const traceBtn = page.getByRole('button', { name: /Execution details/i });
  check(await traceBtn.count() > 0, 'Execution details panel is present');
  if (await traceBtn.count() > 0) {
    await traceBtn.first().click();
    await page.waitForTimeout(300);
    const panelText = await page.locator('body').innerText();
    check(/Parse query|Execute SQL|Generate SQL/i.test(panelText), 'trace shows pipeline stages');

    // Expand the final SQL
    const sqlBtn = page.getByRole('button', { name: /Final SQL executed/i });
    check(await sqlBtn.count() > 0, 'Final SQL toggle present');
    if (await sqlBtn.count() > 0) {
      await sqlBtn.first().click();
      await page.waitForTimeout(200);
      const sqlText = (await page.locator('pre').last().innerText()) || '';
      check(/SELECT/i.test(sqlText), `final SQL shown (${sqlText.length} chars)`);
    }
    await page.screenshot({ path: `${OUT}/03_trace_open.png`, fullPage: true });
  }

  // ── 3. Leave-and-return persistence (Issue 1) ──
  // Use CLIENT-SIDE navigation (nav links), not page.goto which hard-reloads
  // and is not what "leaving the page" means for an SPA user.
  log('SPA-navigate to Explore then back to Advanced');
  await page.getByRole('link', { name: /^Explore$/i }).first().click();
  await page.waitForTimeout(1000);
  const onExplore = /explore/i.test(page.url());
  check(onExplore, `client-side navigated to Explore (url=${page.url()})`);
  await page.getByRole('link', { name: /^Advanced$/i }).first().click();
  await page.waitForTimeout(1000);
  const rowsAfterReturn = await page.locator('table tbody tr').count();
  check(rowsAfterReturn > 0, `results persisted after SPA navigation (${rowsAfterReturn} rows)`);
  await page.screenshot({ path: `${OUT}/04_after_return.png`, fullPage: true });

  // ── 4. Error hygiene ──
  check(pageErrors.length === 0, `no uncaught page errors (${pageErrors.length})`);
  if (pageErrors.length) console.log('  pageErrors:', pageErrors.slice(0, 5));
  // console errors: ignore favicon/404 noise
  const realConsole = consoleErrors.filter((t) => !/favicon|404|net::ERR/i.test(t));
  check(realConsole.length === 0, `no console errors (${realConsole.length})`);
  if (realConsole.length) console.log('  consoleErrors:', realConsole.slice(0, 5));
} catch (e) {
  log('EXCEPTION', e.message);
  await page.screenshot({ path: `${OUT}/99_exception.png` }).catch(() => {});
  failures++;
} finally {
  await browser.close();
  log(`DONE — ${failures} failure(s). Screenshots in ${OUT}`);
  process.exit(failures ? 1 : 0);
}
