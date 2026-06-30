// Phase 27 — capture screenshots of the main pages for human-expert visual
// review, and report console errors per page.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.env.E2E_BASE || 'http://localhost:8000/singledb';
const OUT = '/tmp/p27_shots';
mkdirSync(OUT, { recursive: true });

const pages = [
  ['landing', '/'],
  ['explore', '/explore'],
  ['stats', '/stats'],
  ['discover', '/discover'],
  ['projects', '/projects'],
  ['series', '/series'],
];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
for (const [name, path] of pages) {
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', (e) => errs.push('PAGEERROR ' + e));
  try {
    await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(2500); // let data + charts render
    await page.screenshot({ path: `${OUT}/page_${name}.png`, fullPage: true });
    const real = errs.filter((t) => !/favicon|404|net::ERR|EventSource|SSE/i.test(t));
    console.log(`[shot] ${name.padEnd(9)} OK  console-errors=${real.length}${real.length ? ' :: ' + real.slice(0, 2).join(' | ') : ''}`);
  } catch (e) {
    console.log(`[shot] ${name.padEnd(9)} FAIL ${e.message}`);
  }
  await page.close();
}
await browser.close();
console.log('[shot] done →', OUT);
