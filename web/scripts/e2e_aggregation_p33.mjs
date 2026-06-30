// Phase 33 — verify aggregation ("count by …") queries render a breakdown
// (bar chart + table) in Advanced Search instead of empty sample rows.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.env.E2E_BASE || 'http://localhost:5173/singledb';
const OUT = '/tmp/p33_shots';
mkdirSync(OUT, { recursive: true });
let failures = 0;
const check = (c, m) => { console.log(`[agg] ${c ? 'PASS' : 'FAIL'} — ${m}`); if (!c) failures++; };

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const errs = [];
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
try {
  await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' });
  await page.getByRole('textbox', { name: /natural-language search/i }).fill('count samples by disease category');
  await page.getByRole('button', { name: /^Search/i }).click();
  // Wait for the aggregation panel.
  await page.getByText(/Aggregation —/i).waitFor({ timeout: 60000 });
  const body = await page.locator('body').innerText();
  check(/Aggregation —\s*\d+\s*groups/i.test(body), 'aggregation header with group count');
  check(/neoplasm/i.test(body), 'shows a disease category (neoplasm)');
  check(/%/.test(body), 'shows percentages');
  check((await page.locator('svg .recharts-bar path, svg .recharts-rectangle, .recharts-bar rect').count()) > 0, 'bar chart rendered');
  // The empty sample table should NOT be shown for aggregation.
  const emptyRows = await page.locator('table tbody tr').filter({ hasText: /^—\s*—/ }).count();
  check(emptyRows === 0, `no empty placeholder sample rows (${emptyRows})`);
  await page.screenshot({ path: `${OUT}/agg_render.png`, fullPage: true });
  check(errs.filter((t) => !/favicon|404|net::ERR/i.test(t)).length === 0, `no console errors (${errs.length})`);
} catch (e) {
  console.log('[agg] EXCEPTION', e.message);
  await page.screenshot({ path: `${OUT}/agg_exception.png` }).catch(() => {});
  failures++;
} finally {
  await browser.close();
  console.log(`[agg] DONE — ${failures} failure(s)`);
  process.exit(failures ? 1 : 0);
}
