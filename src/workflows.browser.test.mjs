// Install playwright in an external tools folder, then set PLAYWRIGHT_MODULE to its index.mjs.
// Start Vite on 5176. Run: node --test src/workflows.browser.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { users, reports as originalReports, issues as originalIssues, processingHealth, page as paginate } from './workflow.fixtures.js';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const site = process.env.UI_TEST_URL || 'http://127.0.0.1:5176';
const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
const browser = await chromium.launch({ channel: 'msedge', headless: true });

async function setup(role = 'citizen', mobile = false) {
  const context = await browser.newContext({ viewport: mobile ? { width: 360, height: 800 } : { width: 1440, height: 1000 } });
  const page = await context.newPage(), calls = [], errors = [];
  page.setDefaultTimeout(8000);
  const state = { reports: structuredClone(originalReports), issues: structuredClone(originalIssues), failSubmit: false, failList: false, submissions: 0, keys: [], expire: false, slowDetail: false };
  page.on('pageerror', e => errors.push(e.message));
  await context.addInitScript(role => localStorage.setItem('nagarsaathi_token', role), role);
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    const api = /^\/(?:api\/)?(?:auth|reports|complaints|issues|processing)(?:\/|$)/.test(path);
    if (!api) {
      if (/tile.openstreetmap|fonts.googleapis|fonts.gstatic/.test(url.hostname)) return route.abort();
      return route.continue();
    }
    const endpoint = path.replace(/^\/api/, ''), method = req.method(), token = (req.headers().authorization || '').replace('Bearer ', '');
    calls.push({ endpoint, method, token, body: req.postData(), headers: req.headers() });
    const send = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body), headers: { 'access-control-allow-origin': '*' } });
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' } });
    if (endpoint === '/auth/login') return send({ access_token: JSON.parse(req.postData()).email.split('@')[0] });
    if (endpoint === '/auth/register') return send({ id: 1, role: 'citizen' }, 201);
    if (endpoint === '/auth/logout') return route.fulfill({ status: 204 });
    if (!users[token] || state.expire) return send({ detail: 'Session expired' }, 401);
    if (endpoint === '/auth/me') return send(users[token]);
    if (endpoint === '/processing/health') return token === 'admin' ? send(processingHealth) : send({ detail: 'Forbidden' }, 403);
    if (endpoint === '/complaints') {
      if (state.failList) return send({ detail: 'List unavailable' }, 503);
      if (token === 'nigam') return send({ detail: 'Forbidden' }, 403);
      const items = token === 'admin' ? state.reports.filter(r => !url.searchParams.has('needs_attention') || r.needs_attention) : [state.reports[0]];
      return send(paginate(items, Number(url.searchParams.get('offset') || 0)));
    }
    if (endpoint === '/reports' && method === 'POST') {
      state.submissions++; state.keys.push(req.headers()['idempotency-key']);
      if (state.failSubmit) return send({ detail: 'Submission service temporarily unavailable' }, 503);
      state.reports[0].verification_status = 'pending'; return send(state.reports[0], 201);
    }
    const report = endpoint.match(/^\/reports\/(\d+)$/);
    if (report) {
      if (state.slowDetail) await new Promise(resolve => setTimeout(resolve, 600));
      if (token === 'nigam' || (token === 'citizen' && report[1] !== '1')) return send({ detail: 'Not found' }, 404);
      // Deliberately include technical extras: citizen must not render any of them.
      return send({ ...state.reports.find(r => String(r.id) === report[1]), model_version: 'SECRET-MODEL', confidence: .99, duplicate_of: 12 });
    }
    if (/^\/(issues|reports)\/\d+\/photo$/.test(endpoint)) return route.fulfill({ status: 200, contentType: 'image/png', body: pixel });
    if (endpoint === '/issues') return send(paginate(state.issues, Number(url.searchParams.get('offset') || 0)));
    const issue = endpoint.match(/^\/issues\/(\d+)$/);
    if (issue) return send({ ...state.issues.find(i => String(i.id) === issue[1]), reporter_email: 'PRIVATE-REPORTER@example.test', reports: state.reports });
    const repair = endpoint.match(/^\/issues\/(\d+)\/status$/);
    if (repair && method === 'PATCH') {
      const body = JSON.parse(req.postData()); const issue = state.issues.find(i => String(i.id) === repair[1]);
      issue.status = body.status; state.reports.filter(r => r.issue_id === issue.id).forEach(r => { r.status = body.status; r.status_note = body.note; });
      return send(issue);
    }
    if (/^\/reports\/\d+\/review$/.test(endpoint)) return send({ id: 2, verification_status: 'supported' });
    return send({ detail: 'Fixture endpoint missing: ' + endpoint }, 404);
  });
  await page.goto(site);
  await page.locator('nav[aria-label="Workspace navigation"]').waitFor({ state: 'attached' });
  return { context, page, state, calls, errors };
}
async function navigate(page, name) {
  const toggle = page.getByRole('button', { name: 'Toggle navigation' });
  if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.getByRole('button', { name, exact: true }).click();
}
async function noOverflow(page) { assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); }

try {
  await test('mobile citizen submits without analysis, retries idempotently, tracks pending then repair updates', async () => {
    const { context, page, state, calls, errors } = await setup('citizen', true);
    try {
      await navigate(page, 'Report Issue');
      await page.getByLabel('Description', { exact: true }).fill('Large pothole beside the bus stop');
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
      await page.getByLabel('Road photo').setInputFiles({ name: 'road.png', mimeType: 'image/png', buffer: pixel });
      await page.getByLabel('Latitude', { exact: true }).fill('12.9716'); await page.getByLabel('Longitude', { exact: true }).fill('77.5946');
      await page.getByRole('checkbox').check(); await page.getByRole('button', { name: 'Continue', exact: true }).click();
      await noOverflow(page);
      assert.doesNotMatch(await page.locator('main').innerText(), /Check Photo|confidence|detection|model|duplicate|priority/i);
      state.failSubmit = true; await page.getByRole('button', { name: 'Submit complaint' }).click();
      await page.getByRole('alert').filter({ hasText: 'temporarily unavailable' }).waitFor();
      state.failSubmit = false; await page.getByRole('button', { name: 'Submit complaint' }).click();
      await page.getByText('Thank you for speaking up.').waitFor(); assert.equal(state.submissions, 2); assert.equal(state.keys[0], state.keys[1]);
      assert.ok(state.keys[0]); assert.equal(calls.some(c => /detect|worker|analy/.test(c.endpoint)), false);
      await page.getByRole('button', { name: 'Track this report' }).click(); await page.getByRole('dialog').getByText('Verification pending', { exact: true }).waitFor();
      assert.doesNotMatch(await page.getByRole('dialog').innerText(), /SECRET-MODEL|confidence|duplicate|priority/i);
      await noOverflow(page);
      state.reports[0].verification_status = 'supported';
      await page.getByRole('dialog').getByText('Evidence supports the report', { exact: true }).waitFor({ timeout: 18000 });
      await page.getByRole('button', { name: 'Close details' }).click();
      await navigate(page, 'My Reports');
      state.reports[0].verification_status = 'needs_review'; state.reports[0].status = 'in_progress';
      await page.getByRole('button', { name: 'Refresh reports' }).click();
      await page.getByText('Repair in progress', { exact: true }).waitFor(); await page.getByText('Awaiting a closer review', { exact: true }).waitFor();
      state.reports[0].status = 'resolved'; await page.getByRole('button', { name: 'Refresh reports' }).click(); await page.getByText('Resolved', { exact: true }).waitFor();
      assert.deepEqual(errors, []);
      if (process.env.UI_SCREENSHOT_DIR) { mkdirSync(process.env.UI_SCREENSHOT_DIR, { recursive: true }); await page.screenshot({ path: join(process.env.UI_SCREENSHOT_DIR, 'citizen-mobile.png'), fullPage: true }); }
    } finally { await context.close(); }
  });
  await test('admin sees 100 submissions, paginates, inspects shared issue and exceptions', async () => {
    const { context, page, calls, errors } = await setup('admin');
    try {
      await page.getByText('100 individual submissions', { exact: false }).waitFor(); await page.getByText('Reports are saved while the PC worker is offline.').waitFor();
      await page.getByRole('button', { name: 'Next', exact: true }).click(); await page.getByRole('heading', { name: 'NS-21', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Inspect submission' }).first().click();
      await page.getByRole('dialog').getByRole('button', { name: /Shared issue/ }).click();
      await page.getByRole('dialog').getByText('Automatic priority:', { exact: false }).waitFor();
      await page.getByRole('button', { name: 'Close details' }).click(); await navigate(page, 'Exceptions');
      await page.getByText('Category mismatch needs review').waitFor();
      await page.getByRole('button', { name: 'Inspect submission' }).click();
      await page.getByLabel('Review reason').fill('Reviewed location and evidence; request clarification');
      await page.getByRole('button', { name: 'Record exception review' }).click();
      await page.waitForTimeout(150); assert.ok(calls.some(c => c.endpoint === '/reports/2/review' && c.method === 'PATCH'));
      assert.deepEqual(errors, []); await noOverflow(page);
    } finally { await context.close(); }
  });
  await test('Nigam sees 20 consolidated issues, preserves API priority order and updates repairs', async () => {
    const { context, page, calls, errors } = await setup('nigam', true);
    try {
      await page.getByText('20 consolidated issues', { exact: false }).waitFor();
      assert.equal(await page.getByRole('heading', { name: /^Issue #/ }).count(), 20);
      assert.equal(await page.getByRole('heading', { name: /^Issue #/ }).first().innerText(), 'Issue #100');
      assert.equal(calls.some(c => c.endpoint === '/complaints' || c.endpoint === '/processing/health'), false);
      await page.getByRole('button', { name: 'View issue & repair progress' }).first().click();
      await page.getByRole('dialog').getByText('Distinct accounts', { exact: true }).waitFor();
      assert.doesNotMatch(await page.getByRole('dialog').innerText(), /PRIVATE-REPORTER|NS-1|Processing and grouping|Exception review/);
      await page.getByLabel('Repair status').selectOption('in_progress'); await page.getByLabel('Progress note / decision reason').fill('Crew scheduled for tomorrow');
      await page.getByRole('button', { name: 'Save repair update' }).click();
      await page.getByRole('dialog').locator('p.workflow-notice').filter({ hasText: 'Repair in progress' }).waitFor(); await noOverflow(page);
      assert.ok(calls.some(c => c.endpoint === '/issues/100/status' && JSON.parse(c.body).note === 'Crew scheduled for tomorrow'));
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });
  await test('failed list clears records and Retry restores them', async () => {
    const { context, page, state } = await setup();
    try {
      await page.getByRole('heading', { name: 'NS-1', exact: true }).waitFor(); state.failList = true;
      await page.getByRole('button', { name: 'Refresh reports' }).click(); await page.getByText('List unavailable', { exact: true }).waitFor();
      assert.equal(await page.getByRole('heading', { name: 'NS-1', exact: true }).count(), 0);
      state.failList = false; await page.getByRole('button', { name: 'Retry', exact: true }).click(); await page.getByRole('heading', { name: 'NS-1', exact: true }).waitFor();
    } finally { await context.close(); }
  });
  await test('cross-tab account changes discard stale details; forbidden role routes never fetch', async () => {
    const { context, page, state, calls, errors } = await setup('admin');
    try {
      await page.getByRole('button', { name: 'Inspect submission' }).first().waitFor(); state.slowDetail = true;
      await page.getByRole('button', { name: 'Inspect submission' }).first().click();
      const other = await context.newPage(); await other.goto(site); await other.evaluate(() => localStorage.setItem('nagarsaathi_token', 'nigam'));
      await page.getByText('NAGAR NIGAM WORKSPACE', { exact: true }).first().waitFor();
      await page.getByText('This record is not available in your workspace.').waitFor();
      await page.waitForTimeout(700); assert.equal(await page.getByText('Processing and grouping', { exact: true }).count(), 0);
      assert.equal(calls.some(c => c.token === 'nigam' && c.endpoint.startsWith('/reports/')), false);
      await page.getByRole('button', { name: 'Close details' }).click(); await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
      assert.equal(await page.getByRole('heading', { name: /^Issue #/ }).count(), 0); assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });
  await test('sign-in and public registration use verified server role, not a browser role selector', async () => {
    const { context, page, calls } = await setup();
    try {
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await page.getByLabel('Email address').fill('admin@example.test'); await page.getByLabel('Password', { exact: true }).fill('example-password');
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      await page.getByText('PLATFORM ADMIN WORKSPACE', { exact: true }).first().waitFor();
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await page.getByRole('button', { name: 'New here? Register as a citizen' }).click();
      await page.getByLabel('Full name').fill('New Citizen'); await page.getByLabel('Email address').fill('citizen@example.test');
      await page.getByLabel('Password', { exact: true }).fill('example-password'); await page.getByRole('button', { name: 'Create citizen account', exact: true }).click();
      await page.getByRole('heading', { name: 'Your voice. A better city.' }).waitFor();
      const registration = calls.find(c => c.endpoint === '/auth/register'); assert.equal(JSON.parse(registration.body).role, undefined);
      assert.equal(calls.some(c => /[?&]token=/.test(c.endpoint)), false);
    } finally { await context.close(); }
  });
  await test('expired sessions clear role data and require sign-in', async () => {
    const { context, page, state } = await setup();
    try {
      await page.getByRole('heading', { name: 'NS-1', exact: true }).waitFor(); state.expire = true;
      await page.getByRole('button', { name: 'Refresh reports' }).click(); await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
      assert.equal(await page.getByRole('heading', { name: 'NS-1', exact: true }).count(), 0);
    } finally { await context.close(); }
  });
} finally { await browser.close(); }
