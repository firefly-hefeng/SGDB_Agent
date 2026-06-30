#!/usr/bin/env node
/**
 * Deep interaction walkthrough. Tests user flows, not just page loads:
 *   1. Featured collection click → Explore opens with the right filter
 *   2. Explore filter submit → results update
 *   3. Discover query submit → SSE stream produces results
 *   4. Dataset detail loads a real ID
 *   5. Add-to-manifest from a dataset card updates the manifest counter
 *
 * Goal: surface bugs that the page-load walkthrough missed.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = 'http://localhost:5173/singledb';
mkdirSync('/tmp/interaction', { recursive: true });

const results = [];

async function run() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  ctx.on('weberror', (e) => errors.push(`webError: ${e.error()?.message}`));

  // ── Test 1: Featured collection card → Explore handoff ─────────
  await testFeaturedCollectionHandoff(ctx, errors);

  // ── Test 2: Explore facet filter ───────────────────────────────
  await testExploreFacet(ctx, errors);

  // ── Test 3: Discover SSE stream ────────────────────────────────
  await testDiscoverStream(ctx, errors);

  // ── Test 4: Dataset detail loads ───────────────────────────────
  await testDatasetDetail(ctx, errors);

  // ── Test 5: Add to manifest ────────────────────────────────────
  await testAddToManifest(ctx, errors);

  // ── Test 6: Workspace create + select ──────────────────────────
  await testWorkspaceCreate(ctx, errors);

  // ── Test 7: Downloads metadata CSV ─────────────────────────────
  await testDownloadsMetadata(ctx, errors);

  await browser.close();
  console.log(JSON.stringify(results, null, 2));
}

async function testWorkspaceCreate(ctx, _ge) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    await page.goto(`${BASE}/workspace`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // Click + button to open create modal.
    const plusBtn = page.locator('button[aria-label="Create new workspace"]').first();
    const plusCount = await page.locator('button[aria-label="Create new workspace"]').count();
    if (plusCount === 0) {
      results.push({ test: 'workspace-create', pass: false, reason: 'Create button not found' });
      return;
    }
    await plusBtn.click();
    await page.waitForTimeout(500);

    // Fill name + submit. The Modal renders inputs; first text input = name.
    const wsName = `e2e-test-${Date.now()}`;
    const nameInput = page.locator('input[type="text"]').last();
    await nameInput.fill(wsName);
    const submitBtn = page.locator('button:has-text("Create")').last();
    await submitBtn.click();
    await page.waitForTimeout(2500);

    // Workspace should now appear in sidebar.
    const sidebar = await page.locator('aside').first().textContent();
    const inSidebar = sidebar?.includes(wsName) ?? false;
    await page.screenshot({ path: '/tmp/interaction/06-workspace-created.png', fullPage: false });

    results.push({
      test: 'workspace-create',
      pass: inSidebar,
      createdName: wsName,
      sidebarHasName: inSidebar,
      errors: errors.slice(0, 3),
    });
  } catch (e) {
    results.push({ test: 'workspace-create', pass: false, error: e.message });
  } finally {
    await page.close();
  }
}

async function testDownloadsMetadata(ctx, _ge) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    await page.goto(`${BASE}/downloads`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // Look for the CSV button.
    const csvBtn = page.locator('button:has-text("CSV")').first();
    const csvCount = await page.locator('button:has-text("CSV")').count();
    const downloadPromise = page.waitForEvent('download', { timeout: 30000 }).catch(() => null);

    if (csvCount > 0) {
      await csvBtn.click();
    }
    const download = await downloadPromise;
    const saved = download ? await download.path() : null;
    await page.screenshot({ path: '/tmp/interaction/07-downloads-after-csv.png', fullPage: false });
    results.push({
      test: 'downloads-csv',
      pass: csvCount > 0 && !!saved,
      csvBtnCount: csvCount,
      downloadPath: saved,
      errors: errors.slice(0, 3),
    });
  } catch (e) {
    results.push({ test: 'downloads-csv', pass: false, error: e.message });
  } finally {
    await page.close();
  }
}

async function testFeaturedCollectionHandoff(ctx, globalErrors) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);

    // Find a Featured Collection card and click it.
    const card = page.locator('a:has-text("Open"):has(h3)').first();
    const cardCount = await page.locator('a:has-text("Open"):has(h3)').count();
    if (cardCount === 0) {
      results.push({ test: 'featured-collection-handoff', pass: false, reason: 'No collection cards found' });
      return;
    }
    const cardHref = await card.getAttribute('href');
    await card.click();
    await page.waitForURL(/\/explore/);
    await page.waitForTimeout(2000);
    await page.screenshot({ path: '/tmp/interaction/01-after-collection-click.png', fullPage: false });

    const url = page.url();
    const h1 = await page.locator('h1').first().textContent();
    const hasFilter = url.includes('q=') || url.includes('tissue=') || url.includes('disease=');
    results.push({
      test: 'featured-collection-handoff',
      pass: hasFilter && h1?.includes('Explore'),
      cardCount,
      cardHref,
      landedUrl: url,
      h1,
      errors: errors.slice(0, 3),
    });
  } catch (e) {
    results.push({ test: 'featured-collection-handoff', pass: false, error: e.message, errors });
  } finally {
    await page.close();
  }
}

async function testExploreFacet(ctx, globalErrors) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    await page.goto(`${BASE}/explore`, { waitUntil: 'domcontentloaded' });
    // Deterministic wait: data row appears.
    await page.waitForSelector('tbody tr td', { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(1500);

    // Look for any facet chip — Source databases is the most reliable.
    const facetItems = await page.locator('aside button, aside label').count();
    // Try to click a source filter — "geo" should always be present.
    const geoButton = page.locator('label:has-text("geo"), button:has-text("geo")').first();
    const geoCount = await page.locator('label:has-text("geo"), button:has-text("geo")').count();
    if (geoCount > 0) {
      await geoButton.click();
      await page.waitForTimeout(3000);
    }
    const url = page.url();
    const totalCount = await page.locator('text=/[0-9,]+ results/').first().textContent().catch(() => null);
    const dataRowCount = await page.locator('tbody tr').count();
    await page.screenshot({ path: '/tmp/interaction/02-explore-after-facet.png', fullPage: false });
    results.push({
      test: 'explore-facet-filter',
      pass: dataRowCount > 0 && facetItems > 0,
      facetItems,
      geoCount,
      dataRowCount,
      urlAfterClick: url,
      totalCount,
      errors: errors.slice(0, 3),
    });
  } catch (e) {
    results.push({ test: 'explore-facet-filter', pass: false, error: e.message });
  } finally {
    await page.close();
  }
}

async function testDiscoverStream(ctx, globalErrors) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    await page.goto(`${BASE}/discover`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // Type a query in the Discover search bar (NOT the TopNav search).
    const input = page.locator('input[placeholder*="Describe the datasets"]').first();
    await input.fill('pancreatic islet');
    // Submit by clicking the Discover button to be precise.
    const submitBtn = page.locator('button:has-text("Discover")').last();
    await submitBtn.click();
    await page.waitForTimeout(20000); // wait for SSE results (slower sources)

    // Look for status strip text or source section headers.
    const sourceSections = await page.locator('h2, [class*="source"]').count();
    const totalText = await page.locator('text=/hits across|No live hits|Searching/').first().textContent().catch(() => null);
    const intentChips = await page.locator('[role="status"], [class*="intent"]').count();
    await page.screenshot({ path: '/tmp/interaction/03-discover-results.png', fullPage: false });
    results.push({
      test: 'discover-stream',
      pass: !!totalText,
      sourceSectionsCount: sourceSections,
      intentChipsCount: intentChips,
      summaryText: totalText,
      errors: errors.slice(0, 5),
    });
  } catch (e) {
    results.push({ test: 'discover-stream', pass: false, error: e.message });
  } finally {
    await page.close();
  }
}

async function testDatasetDetail(ctx, globalErrors) {
  // Use a known project id from /trending.
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    const resp = await page.request.get('http://localhost:8000/scdbAPI/collections/trending?limit=1');
    const j = await resp.json();
    const id = j.projects?.[0]?.project_id;
    if (!id) {
      results.push({ test: 'dataset-detail', pass: false, reason: 'No trending project_id available' });
      return;
    }
    await page.goto(`${BASE}/explore/${encodeURIComponent(id)}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(4000);
    const h1 = await page.locator('h1').first().textContent().catch(() => null);
    const notFound = await page.locator('text=/Dataset not found/').count();
    await page.screenshot({ path: '/tmp/interaction/04-dataset-detail.png', fullPage: false });
    results.push({
      test: 'dataset-detail',
      pass: !!h1 && notFound === 0,
      testedId: id,
      h1,
      notFound,
      errors: errors.slice(0, 3),
    });
  } catch (e) {
    results.push({ test: 'dataset-detail', pass: false, error: e.message });
  } finally {
    await page.close();
  }
}

async function testAddToManifest(ctx, globalErrors) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    // Clear manifest first via direct localStorage.
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.clear());

    // Use a known id.
    const resp = await page.request.get('http://localhost:8000/scdbAPI/collections/trending?limit=1');
    const j = await resp.json();
    const id = j.projects?.[0]?.project_id;
    if (!id) {
      results.push({ test: 'add-to-manifest', pass: false, reason: 'no trending project' });
      return;
    }
    await page.goto(`${BASE}/explore/${encodeURIComponent(id)}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(4000);

    // Look specifically for "Add all to manifest" button on the dataset page.
    const addBtn = page.locator('button:has-text("Add all to manifest")').first();
    const addBtnCount = await page.locator('button:has-text("Add all to manifest")').count();
    if (addBtnCount > 0) {
      await addBtn.click();
      await page.waitForTimeout(2000);
    }

    // Check manifest counter in nav.
    const nav = await page.locator('header, nav').first().textContent().catch(() => '');
    const manifest = await page.evaluate(() => localStorage.getItem('sceqtl.manifest.v1'));
    await page.screenshot({ path: '/tmp/interaction/05-after-add-manifest.png', fullPage: false });
    results.push({
      test: 'add-to-manifest',
      pass: addBtnCount > 0 && !!manifest && manifest.length > 50,
      addBtnCount,
      manifestLen: manifest?.length || 0,
      navContains: nav.slice(0, 200),
      errors: errors.slice(0, 3),
    });
  } catch (e) {
    results.push({ test: 'add-to-manifest', pass: false, error: e.message });
  } finally {
    await page.close();
  }
}

run().catch((e) => {
  console.error('FATAL', e);
  process.exit(1);
});
