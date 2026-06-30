#!/usr/bin/env node
/**
 * Run axe-core on every top-level route and report all violations.
 * Also probes basic keyboard nav: tab through 8 elements, check focus
 * is visible (computed outline style is not 'none' or 'auto').
 */
import { chromium } from 'playwright';
import { AxeBuilder } from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = 'http://localhost:5173/singledb';
mkdirSync('/tmp/a11y', { recursive: true });

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
];

const summary = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });

  for (const r of ROUTES) {
    const page = await ctx.newPage();
    await page.goto(`${BASE}${r.path}`, { waitUntil: 'domcontentloaded' });
    // Give it a beat for the SPA to render. Use a tighter wait for
    // pages with auto-fetch; the rest just need React to mount.
    await page.waitForTimeout(3500);

    let violations = [];
    try {
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
        .analyze();
      violations = results.violations;
    } catch (e) {
      summary.push({ name: r.name, error: e.message });
      await page.close();
      continue;
    }

    // Keyboard probe: tab 8 times, check active element exists + outline.
    const tabResults = [];
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab');
      const focusInfo = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const cs = window.getComputedStyle(el);
        return {
          tag: el.tagName,
          label: el.getAttribute('aria-label') || el.textContent?.slice(0, 40) || el.tagName,
          outlineStyle: cs.outlineStyle,
          outlineWidth: cs.outlineWidth,
          outlineColor: cs.outlineColor,
        };
      });
      tabResults.push(focusInfo);
    }

    await page.close();

    summary.push({
      name: r.name,
      url: `${BASE}${r.path}`,
      violationCount: violations.length,
      violations: violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodeCount: v.nodes.length,
        firstHTML: v.nodes[0]?.html?.slice(0, 200),
        firstTarget: v.nodes[0]?.target,
      })),
      keyboardTab: tabResults,
    });
  }

  await browser.close();

  writeFileSync('/tmp/a11y/report.json', JSON.stringify(summary, null, 2));
  // Console summary
  for (const r of summary) {
    if (r.error) {
      console.log(`${r.name.padEnd(15)} ERROR: ${r.error}`);
      continue;
    }
    console.log(`${r.name.padEnd(15)} violations=${r.violationCount}`);
    for (const v of r.violations) {
      console.log(`  [${v.impact}] ${v.id} (×${v.nodeCount}): ${v.help}`);
    }
  }
})();
