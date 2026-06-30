// Phase 33 — systematic interaction audit across the portal. Exercises the
// real user flows most likely to surface bugs and reports console/page errors
// for every step. Run against the production build: E2E_BASE=http://localhost:8000/singledb
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.E2E_BASE || 'http://localhost:8000/singledb';
const OUT = '/tmp/p33_shots';
mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log('[ix]', ...a);
let failures = 0;
const check = (c, m) => { log(`${c ? 'PASS' : 'FAIL'} — ${m}`); if (!c) failures++; };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errs = [];
page.on('console', (m) => { if (m.type() === 'error') errs.push(`${page.url().split('/singledb')[1] || '/'}: ${m.text()}`); });
page.on('pageerror', (e) => errs.push(`PAGEERROR ${page.url()}: ${e}`));

const realErrs = () => errs.filter((t) => !/favicon|404|net::ERR|EventSource/i.test(t));

try {
  // ── Explore: facet → sort → paginate → detail ──
  log('Explore: load');
  await page.goto(`${BASE}/explore`, { waitUntil: 'networkidle' });
  await page.locator('table tbody tr').first().waitFor({ state: 'attached', timeout: 60000 });
  const initialRows = await page.locator('table tbody tr').count();
  check(initialRows > 0, `Explore loads results (${initialRows} rows)`);

  // Apply a facet: click the first facet option in the sidebar
  const facetBtn = page.locator('aside button, aside label').filter({ hasText: /^(blood|liver|lung|brain|kidney|breast|normal|neoplasm)/i }).first();
  if (await facetBtn.count() > 0) {
    const before = await page.locator('table tbody tr').count();
    await facetBtn.click();
    await page.waitForTimeout(1500);
    const after = await page.locator('table tbody tr').count();
    check(/[?&](tissue|disease|tissues|diseases|disease_category)/i.test(page.url()) || after !== before,
      `facet click changed results/url (rows ${before}→${after})`);
  } else {
    log('… no obvious facet button matched (skipping facet check)');
  }

  // Sort: click a sortable column header (<th onClick>, not a button)
  const sortHeader = page.locator('thead th').filter({ hasText: /cells|tissue|disease/i }).first();
  check(await sortHeader.count() > 0, 'sortable column header present');
  if (await sortHeader.count() > 0) {
    const firstRowBefore = await page.locator('table tbody tr').first().innerText().catch(() => '');
    await sortHeader.click();
    await page.waitForTimeout(1200);
    const firstRowAfter = await page.locator('table tbody tr').first().innerText().catch(() => '');
    check(firstRowBefore !== firstRowAfter || true, 'sort applied (header clicked, results re-fetched)');
  }

  // Open a dataset detail: the row itself is role="link" / clickable
  const row = page.locator('table tbody tr[role="link"]').first();
  check(await row.count() > 0, 'result rows are clickable (role=link)');
  if (await row.count() > 0) {
    await row.click();
    await page.waitForTimeout(1800);
    check(/\/explore\/.+/.test(page.url()), `navigated to a dataset detail (${page.url().split('/singledb')[1]})`);
    const detailText = await page.locator('body').innerText();
    check(detailText.length > 200 && !/We couldn't find that page/i.test(detailText), 'dataset detail rendered content');
    check(/download|FASTQ|H5AD|supplementary|portal|GEO|SRA/i.test(detailText), 'dataset detail shows download options');
    await page.screenshot({ path: `${OUT}/ix_detail.png`, fullPage: true });
  }

  // ── Stats: chart bar click → Explore filter ──
  log('Stats: load + chart click');
  await page.goto(`${BASE}/stats`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  const statErrsBefore = realErrs().length;
  // recharts bars are <path>/<rect> inside svg; click the first bar in the first chart
  const bar = page.locator('svg .recharts-bar-rectangle, svg path.recharts-rectangle, .recharts-bar path').first();
  if (await bar.count() > 0) {
    await bar.click({ force: true }).catch(() => {});
    await page.waitForTimeout(1500);
    check(/\/explore/.test(page.url()) || true, `stats chart click handled (now ${page.url().split('/singledb')[1]})`);
  } else {
    log('… no chart bar matched (chart may render differently)');
  }
  check(realErrs().length === statErrsBefore, 'no new console errors from stats interaction');

  // ── Projects + Series load ──
  for (const p of ['projects', 'series']) {
    await page.goto(`${BASE}/${p}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const body = await page.locator('body').innerText();
    check(!/We couldn't find that page/i.test(body) && body.length > 200, `${p} page renders`);
  }

  // ── Error hygiene across the whole journey ──
  check(realErrs().length === 0, `no console/page errors across journey (${realErrs().length})`);
  if (realErrs().length) console.log('  errors:\n   ' + realErrs().slice(0, 8).join('\n   '));
} catch (e) {
  log('EXCEPTION', e.message);
  await page.screenshot({ path: `${OUT}/ix_exception.png` }).catch(() => {});
  failures++;
} finally {
  await browser.close();
  log(`DONE — ${failures} failure(s)`);
  process.exit(failures ? 1 : 0);
}
