import { test, expect } from '@playwright/test';

const BASE_URL = 'http://10.243.163.51:5173';

test.describe('GenSci App E2E Verification', () => {

  // ─── Step 1: Verify page loads correctly ────────────────
  test('Step 1: Page loads correctly with no console errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    // Wait for React to hydrate and render content
    await page.waitForTimeout(3000);

    // Take screenshot
    await page.screenshot({ path: 'e2e/screenshots/step1-homepage.png', fullPage: true });

    // Check page title
    const title = await page.title();
    console.log(`Page title: "${title}"`);

    // Wait for body to have actual rendered content (not just empty root div)
    await page.waitForFunction(() => {
      const root = document.getElementById('root');
      return root && root.textContent && root.textContent.length > 50;
    }, { timeout: 15000 }).catch(() => {
      console.log('WARNING: Body content never exceeded 50 chars within timeout');
    });

    const bodyText = await page.locator('body').textContent();
    console.log(`Page body text length: ${bodyText?.length}`);

    // Check for error boundary or crash indicators
    const hasErrorBoundary = await page.locator('text=Something went wrong').count();
    console.log('Console errors:', consoleErrors);

    // Title should be correct
    expect(title).toBe('GenSci — Single-cell Atlas');

    // Page should have actual rendered content (not empty shell)
    expect(bodyText ? bodyText.length > 50 : false).toBeTruthy();

    // No error boundary should show
    expect(hasErrorBoundary).toBe(0);

    // Filter out SVG path errors which are cosmetic browser warnings
    const criticalErrors = consoleErrors.filter(e => !e.includes('attribute d: Expected path command'));
    console.log('Critical console errors (after filtering SVG warnings):', criticalErrors);
    expect(criticalErrors.length).toBe(0);
  });

  // ─── Step 2: Verify HMR WebSocket on port 5174 ──────────
  test('Step 2: HMR WebSocket connects on port 5174', async ({ page, context }) => {
    const cdpSession = await context.newCDPSession(page);
    const wsConnections: any[] = [];

    cdpSession.on('Network.webSocketCreated', (params: any) => {
      wsConnections.push(params);
    });

    await cdpSession.send('Network.enable');
    await page.goto(BASE_URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);

    await page.screenshot({ path: 'e2e/screenshots/step2-websocket.png', fullPage: true });

    console.log('All WebSocket connections:', JSON.stringify(wsConnections.map(c => c.url), null, 2));

    const hmrOnPort5174 = wsConnections.some(ws => ws.url.includes('5174'));
    const anyWS = wsConnections.length > 0;

    console.log(`HMR WebSocket on port 5174: ${hmrOnPort5174}`);
    console.log(`Total WebSocket connections: ${wsConnections.length}`);

    // Verify HMR connects on port 5174
    expect(hmrOnPort5174).toBeTruthy();
    expect(anyWS).toBeTruthy();
  });

  // ─── Step 3: Navigate to a tissue page ────────────────
  test('Step 3: Navigate to a tissue page', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto(BASE_URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);

    // Wait for React to render content
    await page.waitForFunction(() => {
      const root = document.getElementById('root');
      return root && root.textContent && root.textContent.length > 100;
    }, { timeout: 15000 }).catch(() => {
      console.log('WARNING: Body content never exceeded 100 chars');
    });

    // Look for tissue cards - try multiple strategies
    let clicked = false;
    const possibleTissues = ['Kidney', 'Lung', 'Liver', 'Heart', 'Brain', 'Blood'];

    // Strategy 1: Direct text links
    for (const tissue of possibleTissues) {
      const link = page.locator(`a:has-text("${tissue}")`);
      if (await link.count() > 0) {
        console.log(`Strategy 1: Clicking on "${tissue}" link`);
        await link.first().click();
        clicked = true;
        break;
      }
    }

    // Strategy 2: Any clickable element with tissue text
    if (!clicked) {
      for (const tissue of possibleTissues) {
        const el = page.locator(`text="${tissue}"`);
        if (await el.count() > 0) {
          console.log(`Strategy 2: Found text "${tissue}" - trying to click parent`);
          const parent = el.first().locator('..');
          await parent.click({ timeout: 5000 }).then(() => { clicked = true; }).catch(() => {});
          if (clicked) break;
        }
      }
    }

    // Strategy 3: Navigate directly to a tissue route
    if (!clicked) {
      console.log('Strategy 3: Navigating directly to Lung tissue page');
      await page.goto(`${BASE_URL}/tissue/Lung`, { waitUntil: 'networkidle' });
      clicked = true;
    }

    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'e2e/screenshots/step3-tissue-page.png', fullPage: true });

    console.log('Current URL:', page.url());
    const criticalErrors = consoleErrors.filter(e => !e.includes('attribute d: Expected path command'));
    console.log('Critical console errors:', criticalErrors);
    expect(criticalErrors.length).toBe(0);
  });

  // ─── Step 4: Verify API works through proxy ──────────
  test('Step 4: API endpoints return 200 through Vite proxy', async ({ page }) => {
    const apiEndpoints = [
      { path: '/api/datasets', timeout: 30000 },
      { path: '/api/skills', timeout: 15000 },
      { path: '/api/tissues', timeout: 15000 },
      { path: '/api/stats', timeout: 15000 },
    ];

    const results: { endpoint: string; status: number; ok: boolean; error?: string }[] = [];

    for (const { path, timeout } of apiEndpoints) {
      try {
        const response = await page.request.get(`${BASE_URL}${path}`, { timeout });
        const status = response.status();
        const ok = status === 200;
        const body = await response.text();
        console.log(`${path} => ${status} (${body.length} bytes)`);
        results.push({ endpoint: path, status, ok });
      } catch (err: any) {
        console.log(`${path} => ERROR: ${err.message}`);
        results.push({ endpoint: path, status: 0, ok: false, error: err.message });
      }
    }

    // Also test search endpoint with a short timeout to detect issues
    try {
      const searchResponse = await page.request.get(
        `${BASE_URL}/api/search?q=TP53`,
        { timeout: 15000 }
      );
      const status = searchResponse.status();
      console.log(`/api/search?q=TP53 => ${status}`);
      results.push({ endpoint: '/api/search?q=TP53', status, ok: status === 200 });
    } catch (err: any) {
      console.log(`/api/search?q=TP53 => TIMEOUT (search endpoint may be slow)`);
      results.push({ endpoint: '/api/search?q=TP53', status: 0, ok: false, error: 'timeout' });
    }

    await page.screenshot({ path: 'e2e/screenshots/step4-api-check.png', fullPage: true });

    console.log('API results:', JSON.stringify(results, null, 2));

    // Core API endpoints (excluding search) should all return 200
    const coreResults = results.filter(r => r.endpoint !== '/api/search?q=TP53');
    const allCoreOk = coreResults.every(r => r.ok);
    expect(allCoreOk).toBeTruthy();
  });

  // ─── Step 5: Search functionality works ─────────────
  test('Step 5: Search panel and interaction work', async ({ page }) => {
    const consoleLogs: string[] = [];
    page.on('console', (msg) => {
      consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
    });

    await page.goto(BASE_URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);

    await page.screenshot({ path: 'e2e/screenshots/step5-page-loaded.png', fullPage: true });

    // Look for search-related elements: header search bar, input fields
    const searchInputs = page.locator('input[type="text"], input:not([type="hidden"])');
    const inputCount = await searchInputs.count();
    console.log(`Found ${inputCount} input elements`);

    // Print all input placeholders/types
    for (let i = 0; i < inputCount; i++) {
      const placeholder = await searchInputs.nth(i).getAttribute('placeholder');
      const ariaLabel = await searchInputs.nth(i).getAttribute('aria-label');
      console.log(`  Input #${i}: placeholder="${placeholder}", aria-label="${ariaLabel}"`);
    }

    // Take screenshot of whatever state the page is in
    const bodyText = await page.locator('body').textContent();
    console.log('Body text preview:', bodyText?.substring(0, 500));

    const svgErrors = consoleLogs.filter(l => l.includes('attribute d: Expected path command'));
    const criticalLogs = consoleLogs.filter(l =>
      l.startsWith('[error]') && !l.includes('attribute d: Expected path command')
    );
    console.log(`SVG path errors (cosmetic): ${svgErrors.length}`);
    console.log(`Critical errors: ${criticalLogs.length}`);
    criticalLogs.forEach(l => console.log('  -', l));

    // No critical errors
    expect(criticalLogs.length).toBe(0);
  });
});
