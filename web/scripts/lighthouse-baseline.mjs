#!/usr/bin/env node
/**
 * Lighthouse audit for the 4 most user-visible pages. Outputs a JSON
 * summary keyed by route, with the four canonical category scores.
 */
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(__dirname, '..');
const BASE = 'http://localhost:5173/singledb';
const OUT = '/tmp/lighthouse';
mkdirSync(OUT, { recursive: true });

const ROUTES = [
  { name: 'landing', path: '/' },
  { name: 'explore', path: '/explore' },
  { name: 'stats', path: '/stats' },
  { name: 'discover', path: '/discover' },
];

// Lighthouse needs to be imported via the bundled binary path so we
// don't pull its full CLI. Use a fresh CDP attach.
const { default: lighthouse } = await import(resolve(PROJECT_ROOT, 'node_modules/lighthouse/core/index.js'));

const browser = await chromium.launch({
  headless: true,
  args: ['--remote-debugging-port=9222'],
});

const results = [];

for (const r of ROUTES) {
  console.error(`Auditing ${r.name}...`);
  const url = `${BASE}${r.path}`;

  // Lighthouse 12+ wants port from the browser instance.
  const lhr = await lighthouse(
    url,
    {
      port: 9222,
      logLevel: 'error',
      output: 'json',
      onlyCategories: ['performance', 'accessibility', 'best-practices', 'seo'],
      formFactor: 'desktop',
      screenEmulation: {
        mobile: false,
        width: 1440,
        height: 900,
        deviceScaleFactor: 1,
        disabled: false,
      },
      throttling: {
        rttMs: 40,
        throughputKbps: 10240,
        cpuSlowdownMultiplier: 1,
      },
      throttlingMethod: 'simulate',
    },
  );

  const scores = {
    name: r.name,
    url,
    performance: Math.round((lhr.lhr.categories.performance?.score ?? 0) * 100),
    accessibility: Math.round((lhr.lhr.categories.accessibility?.score ?? 0) * 100),
    best_practices: Math.round((lhr.lhr.categories['best-practices']?.score ?? 0) * 100),
    seo: Math.round((lhr.lhr.categories.seo?.score ?? 0) * 100),
    metrics: {
      fcp: Math.round(lhr.lhr.audits['first-contentful-paint']?.numericValue || 0),
      lcp: Math.round(lhr.lhr.audits['largest-contentful-paint']?.numericValue || 0),
      tbt: Math.round(lhr.lhr.audits['total-blocking-time']?.numericValue || 0),
      cls: Number((lhr.lhr.audits['cumulative-layout-shift']?.numericValue || 0).toFixed(3)),
      si: Math.round(lhr.lhr.audits['speed-index']?.numericValue || 0),
    },
    failingAudits: Object.entries(lhr.lhr.audits)
      .filter(([, a]) => a.score !== null && a.score < 1 && a.scoreDisplayMode !== 'manual' && a.scoreDisplayMode !== 'notApplicable')
      .map(([id, a]) => ({ id, score: a.score, title: a.title }))
      .slice(0, 12),
  };
  results.push(scores);

  writeFileSync(`${OUT}/${r.name}.json`, JSON.stringify(lhr.lhr, null, 2));
}

await browser.close();
writeFileSync(`${OUT}/summary.json`, JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
