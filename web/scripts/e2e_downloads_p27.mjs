// Phase 27 E2E — Downloads page. Seeds the localStorage manifest with a mix of
// a catalog GEO dataset and an external (Discover-style) dataset carrying only
// a URL, then drives the Downloads UI to generate a bash script and verifies
// BOTH datasets appear (Issue 5: "script only had the first entry").
import { chromium } from 'playwright';
import { readFileSync, mkdirSync } from 'node:fs';

const BASE = process.env.E2E_BASE || 'http://localhost:5173/singledb';
const OUT = '/tmp/p27_shots';
mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log('[dl-e2e]', ...a);
let failures = 0;
const check = (c, m) => { log(`${c ? 'PASS' : 'FAIL'} — ${m}`); if (!c) failures++; };

const SEED = {
  entries: [
    { key: 'geo::GSE100118', id: 'GSE100118', source_db: 'GEO', source_url: 'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE100118', download_url: null, file_type: null, title: 'Catalog GEO dataset', added_at: new Date().toISOString() },
    { key: 'geo::EXT-999', id: 'EXT-999', source_db: 'GEO', source_url: 'https://ftp.example.org/EXT-999/', download_url: 'https://ftp.example.org/EXT-999/matrix.h5ad', file_type: 'h5ad', title: 'External Discover dataset', added_at: new Date().toISOString() },
  ],
  updated_at: new Date().toISOString(),
};

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const page = await ctx.newPage();
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('request', (r) => {
  if (r.url().includes('/downloads/manifest') && r.method() === 'POST') {
    log('POST body →', r.postData()?.slice(0, 400));
  }
});

try {
  // Seed the manifest into localStorage before the app reads it.
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.evaluate((seed) => localStorage.setItem('sceqtl.manifest.v1', JSON.stringify(seed)), SEED);

  log('open /downloads');
  await page.goto(`${BASE}/downloads`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/05_downloads.png`, fullPage: true });

  const bodyText = await page.locator('body').innerText();
  check(/Manifest has 2 entries/i.test(bodyText), 'manifest banner shows 2 entries');
  // Both ids should be pre-loaded as chips
  check(/GSE100118/.test(bodyText) && /EXT-999/.test(bodyText), 'both dataset ids pre-loaded');

  // Defaults already select fastq + h5ad + supplementary, which covers the
  // catalog GEO (supplementary) + external h5ad. Just pick the Bash format.
  await page.getByRole('button', { name: /^Bash$/ }).click();

  // Generate + capture the download
  log('click Generate');
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 30000 }),
    page.getByRole('button', { name: /Generate/i }).click(),
  ]);
  const path = await download.path();
  const content = readFileSync(path, 'utf-8');
  check(/GSE100118/.test(content), 'script includes catalog dataset GSE100118');
  check(/EXT-999/.test(content), 'script includes external dataset EXT-999');
  check(/example\.org\/EXT-999/.test(content), 'script includes the external dataset URL');
  check(/set -euo pipefail/.test(content), 'script is production-grade (set -euo pipefail)');
  check(/_retry|download_url|mirror_dir/.test(content), 'script has retry/download helpers');
  log(`downloaded script: ${content.length} chars`);

  check(consoleErrors.filter((t) => !/favicon|404|net::ERR/i.test(t)).length === 0, 'no console errors');
} catch (e) {
  log('EXCEPTION', e.message);
  await page.screenshot({ path: `${OUT}/98_dl_exception.png` }).catch(() => {});
  failures++;
} finally {
  await browser.close();
  log(`DONE — ${failures} failure(s)`);
  process.exit(failures ? 1 : 0);
}
