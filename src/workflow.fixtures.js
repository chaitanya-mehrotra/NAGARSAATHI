// Contract examples for tests only. Never imported by the production application.
export const users = {
  citizen: { id: 1, name: 'Citizen One', email: 'citizen@example.test', role: 'citizen' },
  admin: { id: 2, name: 'Platform Admin', email: 'admin@example.test', role: 'admin' },
  nigam: { id: 3, name: 'Municipal Officer', email: 'nigam@example.test', role: 'nigam' },
};
export const issues = Array.from({ length: 20 }, (_, i) => ({
  id: 100 + i, issue_type: i % 2 ? 'waterlogging' : 'pothole',
  description: `Consolidated road issue ${i + 1}`, status: 'open', published: true,
  latitude: 12.9716 + i * .001, longitude: 77.5946, report_count: 5,
  reporter_count: 4, unique_photo_count: 3, priority_score: 90 - i,
  priority_reason: 'Four distinct accounts and three days waiting contribute to this score.',
  priority_policy_version: 'fixture-v1', grouping_reason: 'Reviewed same-location and visual evidence',
}));
export const reports = Array.from({ length: 100 }, (_, i) => ({
  id: 1 + i, reference: `NS-${1 + i}`, issue_type: i % 2 ? 'waterlogging' : 'pothole',
  description: `Road damage report ${1 + i}`, latitude: 12.9716, longitude: 77.5946,
  created_at: '2026-10-26T05:00:00Z', verification_status: i === 0 ? 'pending' : 'supported',
  status: 'open', processing_status: i === 0 ? 'queued' : 'completed',
  issue_id: issues[Math.floor(i / 5)].id, issue: issues[Math.floor(i / 5)],
  needs_attention: i === 1, exception_reason: i === 1 ? 'Category mismatch needs review' : null,
  grouping_reason: 'Same physical issue supported by location and reviewed evidence',
}));
export const processingHealth = { queued_count: 1, failed_count: 0, worker_status: 'offline', last_heartbeat_at: '2026-10-26T04:00:00Z', message: 'Reports are saved while the PC worker is offline.' };
export const page = (items, offset = 0, limit = 20) => ({ items: items.slice(offset, offset + limit), total: items.length });
