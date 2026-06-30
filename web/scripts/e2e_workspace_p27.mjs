// Phase 27 E2E — Workspace create + entry (Issue 7). Creates a workspace on
// the Workspace page, then saves a real catalog row to it via the star button
// on Explore, and confirms the item lands in the workspace.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.E2E_BASE || 'http://localhost:5173/singledb';
const OUT = '/tmp/p27_shots';
mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log('[ws-e2e]', ...a);
let failures = 0;
const check = (c, m) => { log(`${c ? 'PASS' : 'FAIL'} — ${m}`); if (!c) failures++; };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

const WS_NAME = `E2E WS ${Date.now()}`;
try {
  // ── 1. Create a workspace via the Workspace page ──
  await page.goto(`${BASE}/workspace`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  // Click the "+" create button (aria-label="Create new workspace")
  await page.getByRole('button', { name: /create new workspace/i }).click();
  await page.getByRole('dialog').waitFor({ state: 'visible', timeout: 5000 });
  await page.getByRole('dialog').getByRole('textbox').first().fill(WS_NAME);
  await page.getByRole('dialog').getByRole('button', { name: /^Create$/ }).click();
  await page.waitForTimeout(1200);
  let body = await page.locator('body').innerText();
  check(body.includes(WS_NAME), `created workspace "${WS_NAME}" appears in sidebar`);
  await page.screenshot({ path: `${OUT}/06_workspace_created.png`, fullPage: true });

  // ── 2. Go to Explore, save the first row to the workspace via the star ──
  await page.goto(`${BASE}/explore`, { waitUntil: 'networkidle' });
  await page.locator('table tbody tr').first().waitFor({ state: 'attached', timeout: 60000 });
  const star = page.getByRole('button', { name: /save to workspace/i }).first();
  check(await star.count() > 0, 'star/save button present on result rows');
  await star.click();
  await page.waitForTimeout(500);
  // The popover lists workspaces; click the one we created.
  const wsOption = page.getByRole('button', { name: new RegExp(WS_NAME.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
  check(await wsOption.count() > 0, 'created workspace appears in star popover');
  if (await wsOption.count() > 0) {
    await wsOption.first().click();
    await page.waitForTimeout(1000);
  }
  await page.screenshot({ path: `${OUT}/07_star_saved.png` });

  // ── 3. Back to Workspace; confirm the item landed ──
  await page.goto(`${BASE}/workspace`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  // Click the workspace in the sidebar
  await page.getByRole('link', { name: new RegExp(WS_NAME.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).first().click();
  await page.waitForTimeout(1000);
  body = await page.locator('body').innerText();
  const itemRows = await page.locator('table tbody tr').count();
  check(itemRows >= 1, `workspace detail shows the saved item (${itemRows} row(s))`);
  check(!/This workspace is empty/i.test(body), 'workspace is not shown as empty');
  await page.screenshot({ path: `${OUT}/08_workspace_with_item.png`, fullPage: true });

  // ── 4. Phase 33: "Send to Downloads" bridge ──
  const sendBtn = page.getByRole('button', { name: /send workspace items to downloads/i });
  check(await sendBtn.count() > 0, 'workspace has a "Send to Downloads" button');
  if (await sendBtn.count() > 0) {
    await sendBtn.first().click();
    await page.waitForTimeout(1200);
    check(/\/downloads/.test(page.url()), `navigated to Downloads (url=${page.url()})`);
    const dlBody = await page.locator('body').innerText();
    check(/Manifest has \d+ entr/i.test(dlBody), 'workspace item landed in the download manifest');
  }

  check(consoleErrors.filter((t) => !/favicon|404|net::ERR/i.test(t)).length === 0,
    `no console errors (${consoleErrors.length})`);
  if (consoleErrors.length) console.log('  errors:', consoleErrors.slice(0, 4));
} catch (e) {
  log('EXCEPTION', e.message);
  await page.screenshot({ path: `${OUT}/97_ws_exception.png` }).catch(() => {});
  failures++;
} finally {
  await browser.close();
  log(`DONE — ${failures} failure(s)`);
  process.exit(failures ? 1 : 0);
}
