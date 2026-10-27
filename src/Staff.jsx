import React, { useEffect, useRef, useState } from 'react';
import { request, json } from './services';
import { issueLabels } from './validation';
import { pageOf, repairLabels, verificationLabels, locationLabel, dateLabel } from './workflows';
import { Notice, Pager, Photo, useRemote } from './ui';
import { WorkOrders, IssueHistory } from './Collection';

export function Counts({ item }) {
  return <dl className="workflow-counts"><div><dt>Reports</dt><dd>{item.report_count ?? 'Not supplied'}</dd></div>
    <div><dt>Distinct accounts</dt><dd>{item.reporter_count ?? 'Not supplied'}</dd></div>
    <div><dt>Distinct photos</dt><dd>{item.unique_photo_count ?? 'Not supplied'}</dd></div>
    {item.archived_report_count > 0 && <div><dt>Active / archived</dt><dd>{item.active_report_count} / {item.archived_report_count}</dd></div>}</dl>;
}
export function Priority({ item }) {
  return <section className="workflow-priority"><strong>Automatic priority: {item.priority_score ?? 'Pending'}</strong>
    <p>{item.priority_reason || 'The service has not supplied a priority explanation yet.'}</p>
    {item.priority_policy_version && <small>Policy {item.priority_policy_version}</small>}</section>;
}
export function ProcessingHealth() {
  const state = useRemote(signal => request('/processing/health', { signal }), [], 15000);
  return <section className="card workflow-record"><h2>Processing health</h2><Notice state={state}>{state.data && <>
    <dl className="workflow-counts"><div><dt>Queued jobs</dt><dd>{state.data.queue?.queued ?? state.data.queued_count ?? 'Not supplied'}</dd></div>
      <div><dt>Failed jobs</dt><dd>{state.data.queue?.failed ?? state.data.failed_count ?? 'Not supplied'}</dd></div><div><dt>Worker</dt><dd>{state.data.worker_status || (state.data.worker_online ? 'Online' : 'Offline')}</dd></div></dl>
    <p className="muted">Last worker heartbeat: {dateLabel(state.data.last_heartbeat_at || Math.max(0, ...(state.data.workers || []).map(w => w.last_seen)) || null)}</p>
    {state.data.message && <p>{state.data.message}</p>}</>}</Notice></section>;
}
export function AdminInbox({ openReport, openIssue, exceptions = false }) {
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [exceptions]);
  const state = useRemote(signal => request(`/complaints?limit=20&offset=${offset}${exceptions ? '&needs_attention=true' : ''}`, { signal }).then(pageOf), [offset, exceptions], 15000);
  return <><div className="heading-row"><p className="muted">{exceptions ? 'Cases flagged by the service for human attention.' : 'Every individual submission is retained, including reports linked to the same issue.'}</p>
    <button className="secondary" onClick={state.reload}>Refresh submissions</button></div><ProcessingHealth />
    <Notice state={state}>{state.data && <><p className="workflow-notice">{state.data.total} individual submissions{exceptions ? ' needing attention' : ''} · refreshed every 15 seconds</p>
      <div className="workflow-cards">{state.data.items.map(report => <article className="card workflow-record" key={report.id}><div className="heading-row"><h2>{report.reference || `Report #${report.id}`}</h2>
        <span className={'badge ' + report.issue_type}>{issueLabels[report.issue_type] || 'Road issue'}</span></div><p className="review-description">{report.description}</p>
        <dl className="workflow-facts"><div><dt>Processing</dt><dd>{report.processing_status || 'Not supplied'}</dd></div><div><dt>Verification</dt><dd>{verificationLabels[report.verification_status] || 'Pending'}</dd></div>
          <div><dt>Submitted</dt><dd>{dateLabel(report.created_at)}</dd></div><div><dt>Location</dt><dd>{locationLabel(report)}</dd></div></dl>
        {report.exception_reason && <div className="workflow-exception"><strong>Needs attention</strong><p>{report.exception_reason}</p></div>}
        {report.issue_id != null ? <button className="text-button" onClick={() => openIssue(report.issue_id)}>Shared issue #{report.issue_id} →</button> : <p className="muted">Shared issue assignment pending</p>}
        {report.issue && <><Counts item={report.issue} /><Priority item={report.issue} /></>}
        <p className="muted">Grouping: {report.grouping_reason || 'No grouping explanation supplied yet.'}</p>
        <button className="secondary" onClick={() => openReport(report.id)}>Inspect submission</button></article>)}</div>
      {!state.data.items.length && <p className="workflow-notice">{exceptions ? 'No exceptions need attention.' : 'No submissions yet.'}</p>}
      <Pager total={state.data.total} offset={offset} limit={20} onChange={setOffset} /></>}</Notice></>;
}
export function IssueList({ role, openIssue }) {
  const [offset, setOffset] = useState(0), [queue, setQueue] = useState('active');
  const state = useRemote(signal => request(`/issues?limit=20&offset=${offset}&queue=${queue}&sort=priority`, { signal }).then(pageOf), [offset, queue], 15000);
  return <><div className="heading-row"><p className="muted">{role === 'nigam' ? 'Published consolidated issues only. Work order is supplied automatically by the service.' : 'Shared issues with service-calculated counts and priority.'}</p>
    <label className="workflow-filter">Work queue <select value={queue} onChange={e => { setQueue(e.target.value); setOffset(0); }}><option value="active">Active work</option><option value="resolved">Resolved</option></select></label></div>
    <button className="text-button" onClick={state.reload}>Refresh issues</button><Notice state={state}>{state.data && <><p className="workflow-notice">{state.data.total} consolidated issues · Automatic priority order</p>
      <div className="workflow-cards">{state.data.items.map(issue => <article className="card workflow-record" key={issue.id}>
        <div className="heading-row"><h2>Issue #{issue.id}</h2><span className={'badge ' + issue.issue_type}>{issueLabels[issue.issue_type] || 'Road issue'}</span></div>
        <p className="review-description">{issue.description || 'Inspect this issue for representative evidence.'}</p><span className={'status ' + issue.status}>{repairLabels[issue.status] || 'Awaiting update'}</span>
        <p className="muted">{locationLabel(issue)}</p><Counts item={issue} /><Priority item={issue} />
        <button className="primary" onClick={() => openIssue(issue.id)}>View issue & repair progress</button></article>)}</div>
      {!state.data.items.length && <p className="workflow-notice">{queue === 'active' ? 'No published issues in the active queue.' : 'No resolved issues yet.'}</p>}
      <Pager total={state.data.total} offset={offset} limit={20} onChange={setOffset} /></>}</Notice></>;
}
export function RepairActions({ issue, reload, role }) {
  const [status, setStatus] = useState(issue.status), [note, setNote] = useState(''), [error, setError] = useState(''), [success, setSuccess] = useState(''), [saving, setSaving] = useState(false);
  const controller = useRef(null), lock = useRef(false);
  useEffect(() => () => controller.current?.abort(), []);
  async function save(event) {
    event.preventDefault(); if (lock.current) return;
    if (!note.trim()) { setError('Add a repair update note.'); return; }
    lock.current = true; setSaving(true); setError(''); setSuccess(''); controller.current = new AbortController();
    try {
      await request(`/issues/${issue.id}/status`, { ...json('PATCH', { status, note: note.trim() }), signal: controller.current.signal });
      if (!controller.current.signal.aborted) { setSuccess('Repair progress saved. Linked citizens will see the update.'); setNote(''); reload(); }
    } catch (e) { if (e.name !== 'AbortError') setError(e.message); }
    finally { lock.current = false; if (!controller.current.signal.aborted) setSaving(false); }
  }
  return <form className="workflow-actions" onSubmit={save}><h3>Update repair progress</h3><label htmlFor="repair-status">Repair status</label>
    <select id="repair-status" value={status} onChange={e => setStatus(e.target.value)}>{Object.entries(repairLabels).filter(([value]) => (role !== 'nigam' || value !== 'rejected') && (!issue.work_order || value !== 'resolved' || issue.status === 'resolved')).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
    <label htmlFor="repair-note">Progress note / decision reason</label><textarea id="repair-note" maxLength={1000} rows={3} value={note} onChange={e => setNote(e.target.value)} required />
    <p className="muted">{issue.pending_repair ? 'Repair evidence awaits independent approval below.' : issue.work_order ? 'Assigned work needs repair photos and independent approval before resolution.' : 'The service authorizes and audits this action. Closing an issue requires a recorded reason.'}</p>
    {error && <p className="error-box" role="alert">{error}</p>}{success && <p role="status">{success}</p>}<button className="primary" disabled={saving || issue.pending_repair}>{saving ? 'Saving…' : 'Save repair update'}</button></form>;
}
export function ExceptionReview({ report, reload }) {
  const [decision, setDecision] = useState('needs_review'), [reason, setReason] = useState(''), [error, setError] = useState(''), [saving, setSaving] = useState(false);
  const controller = useRef(null), lock = useRef(false);
  useEffect(() => () => controller.current?.abort(), []);
  async function act(event) {
    event.preventDefault(); if (lock.current) return;
    if (!reason.trim()) { setError('Explain the review decision.'); return; }
    lock.current = true; setSaving(true); setError(''); controller.current = new AbortController();
    try {
      await request(`/reports/${report.id}/review`, { ...json('PATCH', { verification_status: decision, reason: reason.trim() }), signal: controller.current.signal });
      if (!controller.current.signal.aborted) reload();
    } catch (e) { if (e.name !== 'AbortError') setError(e.message); }
    finally { lock.current = false; if (!controller.current.signal.aborted) setSaving(false); }
  }
  return <form className="workflow-actions" onSubmit={act}><h3>Exception review</h3><p className="muted">Use for cases flagged by processing. Ordinary submissions proceed automatically.</p>
    <label htmlFor="decision">Evidence decision</label><select id="decision" value={decision} onChange={e => setDecision(e.target.value)}>
      <option value="needs_review">Keep for review</option><option value="supported">Supporting evidence reviewed</option><option value="not_supported">Evidence not confirmed — allow follow-up</option></select>
    <label htmlFor="reason">Review reason</label><textarea id="reason" value={reason} rows={3} maxLength={1000} required onChange={e => setReason(e.target.value)} />
    {error && <p className="error-box" role="alert">{error}</p>}<button className="secondary" disabled={saving}>{saving ? 'Saving…' : 'Record exception review'}</button></form>;
}
export function IssueDetail({ id, role }) {
  const state = useRemote(signal => request(`/issues/${id}`, { signal }), [id], 15000);
  return <Notice state={state}>{state.data && <><p className="workflow-notice">{issueLabels[state.data.issue_type] || 'Road issue'} · {repairLabels[state.data.status] || 'Awaiting update'}</p>
    <Photo path={`/issues/${id}/photo`} alt="Representative evidence for the consolidated issue" /><p className="review-description">{state.data.description}</p>
    <p>Location: {locationLabel(state.data)}</p><Counts item={state.data} /><Priority item={state.data} />
    {role === 'admin' && <p>Grouping: {state.data.grouping_reason || 'Not supplied'}</p>}
    <RepairActions key={state.data.id + ':' + state.data.status} issue={state.data} reload={state.reload} role={role} />
    <WorkOrders issue={state.data} role={role} refreshIssue={state.reload} /><IssueHistory id={id} /></>}</Notice>;
}
