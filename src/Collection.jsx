import React, { useEffect, useRef, useState } from 'react';
import { request, json, setSession } from './services';
import { Notice, Pager, Photo, useRemote } from './ui';
import { dateLabel, pageOf } from './workflows';

export function GoogleSignIn() {
  const [error, setError] = useState(''), root = useRef(null);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    async function initialize() {
      const options = await request('/auth/options', { signal: controller.signal });
      if (!options.google_client_id || !active) return;
      const challenge = await request('/auth/google/challenge', { method: 'POST', signal: controller.signal });
      if (!window.google?.accounts?.id) await new Promise((resolve, reject) => {
        let script = document.getElementById('google-identity');
        const fail = () => reject(new Error('Google sign-in could not load. You can use your password.'));
        if (!script) {
          script = document.createElement('script'); script.id = 'google-identity'; script.src = 'https://accounts.google.com/gsi/client'; script.async = true;
          script.addEventListener('load', resolve, { once: true }); script.addEventListener('error', fail, { once: true }); document.head.appendChild(script);
        } else { script.addEventListener('load', resolve, { once: true }); script.addEventListener('error', fail, { once: true }); }
      });
      if (!active) return;
      window.google.accounts.id.initialize({ client_id: options.google_client_id, nonce: challenge.nonce, auto_select: false,
        callback: async result => {
          if (!active) return;
          try {
            const session = await request('/auth/google', { ...json('POST', { credential: result.credential }), signal: controller.signal });
            if (active && session.access_token) setSession(session.access_token);
          } catch (e) { if (active && e.name !== 'AbortError') setError(e.message); }
        } });
      window.google.accounts.id.renderButton(root.current, { type: 'standard', theme: 'outline', size: 'large', text: 'continue_with', width: 250 });
    }
    initialize().catch(e => { if (active && e.name !== 'AbortError') setError(e.message); });
    return () => { active = false; controller.abort(); };
  }, []);
  return <div className="collection-google"><div ref={root} />{error && <p className="muted" role="status">{error}</p>}</div>;
}

export function ReportModeration({ report, reload }) {
  const [reason, setReason] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function save(event) {
    event.preventDefault(); if (busy) return;
    if (reason.trim().length < 3) { setError('Explain why this report should be archived or restored.'); return; }
    setBusy(true); setError('');
    try {
      await request(`/moderation/reports/${report.id}/${report.archived_at ? 'restore' : 'archive'}`, json('POST', { reason: reason.trim() }));
      setReason(''); reload();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <form className="workflow-actions" onSubmit={save}><h3>{report.archived_at ? 'Restore archived report' : 'Archive report'}</h3>
    <p className="muted">Archiving is reversible. Original photos, membership and historical counts are retained. Duplicate reports should be grouped instead.</p>
    {report.archived_at && <p>Archived: {dateLabel(report.archived_at)} · {report.archive_reason}</p>}
    <label htmlFor="archive-reason">Moderation reason</label><textarea id="archive-reason" required minLength={3} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} />
    {error && <p className="error-box" role="alert">{error}</p>}<button className="secondary" disabled={busy}>{busy ? 'Saving…' : report.archived_at ? 'Restore report' : 'Archive report'}</button></form>;
}

export function Archive({ openReport }) {
  const [offset, setOffset] = useState(0);
  const state = useRemote(signal => request(`/moderation/reports?limit=20&offset=${offset}`, { signal }).then(pageOf), [offset], 15000);
  return <Notice state={state}>{state.data && <><p className="workflow-notice">{state.data.total} archived reports. Only platform administrators can access this archive.</p>
    <div className="workflow-cards">{state.data.items.map(report => <article className="card workflow-record" key={report.id}><h2>{report.reference}</h2>
      <p>{report.description}</p><p className="muted">{report.archive_reason} · {dateLabel(report.archived_at)}</p>
      <button className="secondary" onClick={() => openReport(report.id)}>Inspect or restore report</button></article>)}</div>
    <Pager total={state.data.total} offset={offset} limit={20} onChange={setOffset} /></>}</Notice>;
}

function AssignmentForm({ id, version, reload }) {
  const accounts = useRemote(signal => request('/work/accounts', { signal }), []);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function save(event) {
    event.preventDefault(); if (busy) return;
    const form = new FormData(event.currentTarget); setError(''); setBusy(true);
    try {
      await request(`/issues/${id}/assignment`, json('PUT', { assigned_to: Number(form.get('account')), team: form.get('team'), note: form.get('note'), expected_version: version })); reload();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <Notice state={accounts}><form className="workflow-actions" onSubmit={save}><h3>{version ? 'Change assignment' : 'Assign repair work'}</h3>
    <label htmlFor="assigned-account">Responsible staff account</label><select id="assigned-account" name="account" required>{accounts.data?.map(a => <option value={a.id} key={a.id}>{a.name} · {a.role}</option>)}</select>
    <label htmlFor="assigned-team">Repair team</label><input id="assigned-team" name="team" required maxLength={100} />
    <label htmlFor="assigned-note">Assignment note</label><textarea id="assigned-note" name="note" required minLength={3} maxLength={1000} />
    {error && <p className="error-box" role="alert">{error}</p>}<button className="secondary" disabled={busy}>{busy ? 'Saving…' : 'Save assignment'}</button></form></Notice>;
}

function RepairUpload({ id, version, reload }) {
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), key = useRef(crypto.randomUUID());
  async function save(event) {
    event.preventDefault(); if (busy) return;
    const body = new FormData(event.currentTarget); body.set('expected_version', String(version)); setBusy(true); setError('');
    try {
      await request(`/issues/${id}/repairs`, { method: 'POST', body, headers: { 'Idempotency-Key': key.current } }); key.current = crypto.randomUUID(); reload();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <form className="workflow-actions" onSubmit={save} onChange={() => { key.current = crypto.randomUUID(); }}><h3>Submit completed repair</h3>
    <p className="muted">Only the assigned account can submit. A different platform administrator must approve the repair before citizens see it as resolved.</p>
    <label htmlFor="repair-evidence">Repair photo</label><input id="repair-evidence" name="image" type="file" required accept="image/jpeg,image/png,image/webp" />
    <label htmlFor="repair-evidence-note">Completed work note</label><textarea id="repair-evidence-note" name="note" required minLength={3} maxLength={1000} />
    {error && <p className="error-box" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy ? 'Submitting…' : 'Submit repair for approval'}</button></form>;
}

function RepairReview({ issueId, repairId, version, reload }) {
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function save(event) {
    event.preventDefault(); if (busy) return;
    const data = new FormData(event.currentTarget); setBusy(true); setError('');
    try { await request(`/issues/${issueId}/repairs/${repairId}/review`, json('POST', { expected_version: version, decision: data.get('decision'), note: data.get('note') })); reload(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <form className="workflow-actions" onSubmit={save}><h3>Independent repair review</h3>
    <label htmlFor={`repair-decision-${repairId}`}>Decision</label><select id={`repair-decision-${repairId}`} name="decision"><option value="verified">Approve repair</option><option value="rejected">Return for more work</option></select>
    <label htmlFor={`repair-review-${repairId}`}>Review note</label><textarea id={`repair-review-${repairId}`} name="note" required minLength={3} maxLength={1000} />
    {error && <p className="error-box" role="alert">{error}</p>}<button className="secondary" disabled={busy}>{busy ? 'Saving…' : 'Record repair review'}</button></form>;
}

export function WorkOrders({ issue, role, refreshIssue }) {
  const state = useRemote(signal => request(`/issues/${issue.id}/work`, { signal }), [issue.id, issue.status], 15000);
  const reload = () => { state.reload(); refreshIssue(); };
  return <section className="workflow-actions"><h3>Repair work order</h3><Notice state={state}>{state.data && <>
    {state.data.assignment ? <p><strong>{state.data.assignment.team}</strong> · {state.data.assignment.note}</p> : <p className="muted">No team assigned yet. Assign a team to require repair photos and independent approval.</p>}
    {role === 'admin' && !['resolved', 'rejected'].includes(issue.status) && !state.data.repairs.some(r => r.state === 'pending') && <AssignmentForm id={issue.id} version={state.data.assignment?.version || 0} reload={reload} />}
    {state.data.can_submit && state.data.assignment && !['resolved', 'rejected'].includes(issue.status) && !state.data.repairs.some(r => r.state === 'pending') && <RepairUpload id={issue.id} version={state.data.assignment.version} reload={reload} />}
    {state.data.repairs.map(repair => <article key={repair.id} className="collection-repair"><h4>Repair evidence · {repair.state}</h4><Photo path={repair.photo_url} alt="Submitted repair evidence" /><p>{repair.note}</p>
      <p className="muted">Submitted {dateLabel(repair.submitted_at)}{repair.review_note && ` · ${repair.review_note}`}</p>
      {role === 'admin' && repair.can_review && repair.state === 'pending' && <RepairReview issueId={issue.id} repairId={repair.id} version={state.data.assignment.version} reload={reload} />}</article>)}
  </>}</Notice></section>;
}

export function IssueHistory({ id }) {
  const state = useRemote(signal => request(`/issues/${id}/history`, { signal }), [id], 15000);
  return <section className="workflow-actions"><h3>Activity history</h3><Notice state={state}><ol className="collection-timeline">{state.data?.map((event, i) => {
    let details = {}; try { details = JSON.parse(event.details); } catch { /* Historical plain text is optional. */ }
    return <li key={i}><strong>{event.event.replaceAll('_', ' ')}</strong><p>{details.note || details.reason || details.grouping_reason || ''}</p><small>{dateLabel(event.created_at)}</small></li>;
  })}</ol></Notice></section>;
}
