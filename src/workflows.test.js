import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { pageOf, routeFromHash, roleCanOpen, verificationHelp } from './workflows.js';
import { issues, reports } from './workflow.fixtures.js';

test('fixture models 100 reports and 20 actual issues with repeated accounts', () => {
  assert.equal(reports.length, 100); assert.equal(issues.length, 20);
  assert.equal(new Set(reports.map(r => r.issue_id)).size, 20);
  assert.equal(issues[0].report_count, 5); assert.equal(issues[0].reporter_count, 4);
});
test('pagination requires server total rather than counting the current page', () => {
  assert.equal(pageOf({ items: reports.slice(0, 20), total: 100 }).total, 100);
  assert.throws(() => pageOf(reports)); assert.throws(() => pageOf({ items: [], total: '100' }));
});
test('role navigation restricts detail types; backend still authorizes every record', () => {
  assert.equal(roleCanOpen('citizen', routeFromHash('#/issues/100')), false);
  assert.equal(roleCanOpen('nigam', routeFromHash('#/reports/1')), false);
  assert.equal(roleCanOpen('admin', routeFromHash('#/reports/1')), true);
  assert.equal(routeFromHash('#/reports/<script>'), null);
});
test('pending and unsupported tracking avoid fraud verdicts', () => {
  assert.match(verificationHelp.pending, /saved/);
  assert.match(verificationHelp.not_supported, /does not mean your report is false/);
});
test('citizen component contains no technical evidence or analysis API calls', () => {
  const citizen = readFileSync(new URL('./Citizen.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(citizen, /Check Photo|confidence|bbox|YOLO|duplicate|priority|\/dev\/detect/);
  const services = readFileSync(new URL('./services.js', import.meta.url), 'utf8');
  assert.match(services, /Idempotency-Key/); assert.doesNotMatch(services, /\/worker\/|\/dev\/detect|searchParams.set\(['"]token/);
});
