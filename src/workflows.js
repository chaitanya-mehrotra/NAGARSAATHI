// Presentation only: the API owns verification, grouping, counts, ranking and access.
export const verificationLabels = {
  pending: 'Verification pending', supported: 'Evidence supports the report',
  needs_review: 'Awaiting a closer review', not_supported: 'More information may be needed',
};
export const repairLabels = { open: 'Awaiting action', in_progress: 'Repair in progress', resolved: 'Resolved', rejected: 'Closed with a decision' };
export const verificationHelp = {
  pending: 'Your report is saved. Verification will continue when processing is available.',
  supported: 'The submitted evidence supports your report. You can track repair progress here.',
  needs_review: 'Your report is saved and needs a closer look. No new upload is needed unless requested.',
  not_supported: 'The supplied evidence could not be confirmed. This does not mean your report is false. It remains available for review.',
};
export const roleLabels = { citizen: 'Citizen workspace', admin: 'Platform admin workspace', nigam: 'Nagar Nigam workspace' };
export function routeFromHash(hash) {
  const match = hash.match(/^#\/(reports|issues)\/([a-zA-Z0-9-]+)$/);
  return match ? { kind: match[1], id: match[2] } : null;
}
export function pageOf(data) {
  if (!data || !Array.isArray(data.items) || !Number.isInteger(data.total) || data.total < 0) {
    throw new Error('The service returned an invalid list. Please retry.');
  }
  return data;
}
export function locationLabel(item) {
  return Number.isFinite(item.latitude) && Number.isFinite(item.longitude)
    ? `${item.latitude.toFixed(5)}, ${item.longitude.toFixed(5)}` : 'Location not supplied';
}
export function dateLabel(value) {
  if (!value) return 'Date not supplied';
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? 'Date not supplied' : date.toLocaleString();
}
export function roleCanOpen(role, route) {
  return route && (role === 'admin' || (role === 'citizen' && route.kind === 'reports') || (role === 'nigam' && route.kind === 'issues'));
}
