#!/usr/bin/env node
/**
 * Walks every top-level route in headless Chromium, captures console
 * errors / pageerrors / failed requests, and screenshots each page.
 * Reports a JSON summary to stdout.
 *
 * Assumes:
 *   - Vite dev server running at http://localhost:5173/singledb
 *   - Backend API running at http://localhost:8765
 */
import { chromium } from 'playwright';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const BASE = 'http://localhost:5173/singledb';
const OUT = '/tmp/walkthrough';
mkdirSync(OUT, { recursive: true });

const ROUTES = [
  { name: 'landing', path: '/' },
  { name: 'explore', path: '/explore' },
  { name: 'projects', path: '/projects' },
  { name: 'series', path: '/series' },
  { name: 'discover', path: '/discover' },
  { name: 'search', path: '/search' },
  { name: 'stats', path: '/stats' },
  { name: 'downloads', path: '/downloads' },
  { name: 'workspace', path: '/workspace' },
  { name: 'explore-with-filter', path: '/explore?tissue=brain' },
  { name: 'discover-with-query', path: '/discover?q=alzheimer+hippocampus' },
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  const report = [];

  for (const r of ROUTES) {
    const page = await ctx.newPage();
    const errors = [];
    const warns = [];
    const failedReqs = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
      if (msg.type() === 'warning') warns.push(msg.text());
    });
    page.on('pageerror', (err) => errors.push(`PAGEERROR ${err.message}`));
    page.on('requestfailed', (req) =>
      failedReqs.push(`${req.method()} ${req.url()} — ${req.failure()?.errorText}`),
    );
    const url = `${BASE}${r.path}`;
    const started = Date.now();
    let navOk = true;
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 });
      // Wait for React mount + a beat for initial fetches.
      await page.waitForLoadState('load', { timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(2000);
    } catch (e) {
      navOk = false;
      errors.push(`NAV_FAIL ${e.message}`);
    }
    // Give async state another beat
    await page.waitForTimeout(800);
    const elapsed = Date.now() - started;
    const title = await page.title().catch(() => '');
    const h1 = await page.locator('h1').first().textContent().catch(() => null);
    const visible = await page.locator('body').isVisible().catch(() => false);

    const png = join(OUT, `${r.name}.png`);
    try {
      await page.screenshot({ path: png, fullPage: true });
    } catch (e) {
      errors.push(`SCREENSHOT_FAIL ${e.message}`);
    }

    report.push({
      name: r.name,
      url,
      elapsedMs: elapsed,
      navOk,
      title,
      h1: h1?.slice(0, 120) ?? null,
      visible,
      errors,
      warns: warns.slice(0, 5),
      failedReqs: failedReqs.slice(0, 8),
      screenshot: png,
    });
    await page.close();
  }

  await browser.close();
  writeFileSync(join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
})();
