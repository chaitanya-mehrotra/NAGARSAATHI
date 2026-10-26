import React, { useEffect, useRef, useState } from 'react';
import { Check, MapPin, Upload } from 'lucide-react';
import ComplaintMap from './Map';
import { request, submit } from './services';
import { issueLabels, validatePhoto } from './validation';
import { verificationLabels, verificationHelp, repairLabels, locationLabel, pageOf } from './workflows';
import { Notice, Pager, useRemote } from './ui';

const fresh = () => ({ issue_type: 'pothole', description: '', file: null, latitude: '', longitude: '', confirmed: false });
export function CitizenSubmit({ openReport }) {
  const [form, setForm] = useState(fresh), [step, setStep] = useState(1), [error, setError] = useState('');
  const [saving, setSaving] = useState(false), [success, setSuccess] = useState(null), [preview, setPreview] = useState('');
  const key = useRef(crypto.randomUUID()), inFlight = useRef(false), controller = useRef(null), alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; controller.current?.abort(); }; }, []);
  useEffect(() => {
    if (!form.file) { setPreview(''); return; }
    const url = URL.createObjectURL(form.file); setPreview(url); return () => URL.revokeObjectURL(url);
  }, [form.file]);
  function change(field, value) {
    key.current = crypto.randomUUID(); // A changed payload is a new submission; unchanged retries reuse the key.
    setForm(f => ({ ...f, [field]: value, ...(field === 'latitude' || field === 'longitude' ? { confirmed: false } : {}) }));
  }
  function validate() {
    if (form.description.trim().length < 10 || form.description.trim().length > 500) return 'Describe the issue in 10–500 characters.';
    if (step === 1) return '';
    const photoError = validatePhoto(form.file);
    if (photoError) return photoError;
    if (form.latitude === '' || form.longitude === '' || !Number.isFinite(Number(form.latitude)) || !Number.isFinite(Number(form.longitude))
      || Math.abs(Number(form.latitude)) > 90 || Math.abs(Number(form.longitude)) > 180) return 'Place a pin or enter valid latitude and longitude.';
    if (!form.confirmed) return 'Confirm that the location marks the actual issue.';
    return '';
  }
  async function save(event) {
    event.preventDefault();
    if (inFlight.current) return;
    const invalid = validate(); if (invalid) { setError(invalid); return; }
    if (step < 3) { setStep(step + 1); setError(''); return; }
    inFlight.current = true; setSaving(true); setError(''); controller.current = new AbortController();
    try {
      const saved = await submit({ ...form, description: form.description.trim() }, key.current, controller.current.signal);
      if (!saved?.id) throw new Error('The service did not return a tracking number. Retry with the same submission.');
      if (alive.current) setSuccess(saved);
    } catch (e) { if (alive.current && e.name !== 'AbortError') setError(e.message + ' Your details are still here; retrying will use the same submission key.'); }
    finally { inFlight.current = false; if (alive.current) setSaving(false); }
  }
  if (success) return <section className="success card" aria-live="polite"><div className="success-icon"><Check size={32} /></div>
    <h2>Thank you for speaking up.</h2><p>Your report is saved. Keep your tracking number.</p><strong className="tracking-number">{success.reference || `Report #${success.id}`}</strong>
    <p>{verificationHelp[success.verification_status] || verificationHelp.pending}</p>
    <div className="button-row"><button className="primary" onClick={() => openReport(success.id)}>Track this report</button>
      <button className="secondary" onClick={() => { setForm(fresh()); setStep(1); setSuccess(null); key.current = crypto.randomUUID(); }}>Report another issue</button></div>
  </section>;
  const point = form.latitude !== '' && form.longitude !== '' && Number.isFinite(Number(form.latitude)) && Number.isFinite(Number(form.longitude))
    && Math.abs(Number(form.latitude)) <= 90 && Math.abs(Number(form.longitude)) <= 180 ? [Number(form.latitude), Number(form.longitude)] : null;
  return <div className="workflow-form-layout"><form className="card workflow-form" onSubmit={save}>
    <div className="steps" aria-label="Submission steps">{['Describe', 'Photo & location', 'Review & submit'].map((label, i) =>
      <div key={label} className={step === i + 1 ? 'current' : ''} aria-current={step === i + 1 ? 'step' : undefined}><span>{i + 1}</span>{label}</div>)}</div>
    {step === 1 && <><div className="section-number">STEP 01</div><h2>What needs attention?</h2><p className="muted">Tell us what you noticed in your neighbourhood.</p>
      <label className="field-label" htmlFor="category">Issue category</label><select id="category" value={form.issue_type} onChange={e => change('issue_type', e.target.value)}>
        {Object.entries(issueLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <label className="field-label" htmlFor="description">Description</label><textarea id="description" rows={6} maxLength={500} value={form.description}
        placeholder="Describe the problem and where to find it. Avoid personal information." onChange={e => change('description', e.target.value)} />
      <div className="field-foot"><span>10–500 characters</span><span>{form.description.length}/500</span></div></>}
    {step === 2 && <><div className="section-number">STEP 02</div><h2>A clearer picture. An exact location.</h2>
      <label className="field-label" htmlFor="photo"><Upload size={16} /> Road photo</label><input id="photo" type="file" accept="image/jpeg,image/png,image/webp" onChange={e => {
        const file = e.target.files?.[0]; if (!file) return; const invalid = validatePhoto(file); setError(invalid); if (!invalid) change('file', file);
      }} /><p className="muted">JPEG, PNG or WebP · Up to 10 MB. The server validates your image.</p>
      {preview && <div className="photo-preview"><img src={preview} alt="Your selected road photo" /></div>}
      <div className="picker-map"><ComplaintMap point={point} onPoint={p => { key.current = crypto.randomUUID(); setForm(f => ({ ...f, latitude: p[0], longitude: p[1], confirmed: false })); }} /></div>
      <p className="muted">Tap the map, use your location, or enter coordinates below. You can submit even if map tiles cannot load.</p>
      <div className="coordinates">{[['latitude', 'Latitude', -90, 90], ['longitude', 'Longitude', -180, 180]].map(([field, label, min, max]) =>
        <label key={field}>{label}<input aria-label={label} type="number" step="any" min={min} max={max} value={form[field]} onChange={e => change(field, e.target.value)} /></label>)}</div>
      <label className="checkbox"><input type="checkbox" checked={form.confirmed} onChange={e => change('confirmed', e.target.checked)} />I confirm this is the actual issue location.</label></>}
    {step === 3 && <><div className="section-number">STEP 03</div><h2>Ready to make a difference?</h2><p className="muted">Review your details before sending.</p>
      <span className={'badge ' + form.issue_type}>{issueLabels[form.issue_type]}</span><p className="review-description">{form.description}</p>
      {preview && <img className="workflow-photo" src={preview} alt="Road photo to submit" />}<p><MapPin size={14} /> {locationLabel({ latitude: Number(form.latitude), longitude: Number(form.longitude) })}</p>
      <p className="workflow-notice">Your photo, description and location will be used to review this report and coordinate repairs. Avoid including personal information.</p></>}
    {error && <div className="error-box" role="alert">{error}</div>}
    <div className="form-footer"><button className="secondary" type="button" disabled={step === 1 || saving} onClick={() => { setStep(step - 1); setError(''); }}>Back</button>
      <button className="primary" disabled={saving} type="submit">{saving ? 'Saving report…' : step === 3 ? 'Submit complaint' : 'Continue'}</button></div>
  </form><aside className="report-help"><span className="mini-icon"><MapPin /></span><h2>Small reports. Better neighbourhoods.</h2>
    <p>A clear photo and an accurate location help the right team find the problem.</p><p>Your report is saved first. You can return to My Reports to follow verification and repairs.</p></aside></div>;
}
export function TrackingStatus({ report }) {
  const verification = report.verification_status || 'pending';
  return <section className="workflow-statuses" aria-label="Report progress"><div><small>Verification</small><strong>{verificationLabels[verification] || 'Awaiting an update'}</strong>
    <p>{report.verification_message || verificationHelp[verification] || verificationHelp.pending}</p></div><div><small>Repair progress</small>
    <strong>{repairLabels[report.status] || 'Awaiting an update'}</strong>{report.status_note && <p>{report.status_note}</p>}</div></section>;
}
export function CitizenReports({ openReport }) {
  const [offset, setOffset] = useState(0), [tracking, setTracking] = useState(''), [error, setError] = useState('');
  const state = useRemote(signal => request(`/complaints?mine=true&limit=20&offset=${offset}`, { signal }).then(pageOf), [offset], 15000);
  return <><div className="heading-row"><p className="muted">Only your saved reports appear here. Updates refresh every 15 seconds.</p><button className="secondary" onClick={state.reload}>Refresh reports</button></div>
    <form className="workflow-track" onSubmit={e => { e.preventDefault(); if (!/^[a-zA-Z0-9-]+$/.test(tracking.trim())) { setError('Enter the report ID from your confirmation.'); return; } setError(''); openReport(tracking.trim()); }}>
      <label htmlFor="tracking">Track a report by ID</label><input id="tracking" value={tracking} onChange={e => setTracking(e.target.value)} placeholder="Report ID" /><button className="secondary">Track report</button>
    </form>{error && <p role="alert">{error}</p>}<Notice state={state}>{state.data && <>
      <div className="workflow-cards">{state.data.items.map(report => <article key={report.id} className="card workflow-record"><div className="heading-row"><h2>{report.reference || `Report #${report.id}`}</h2><span className={'badge ' + report.issue_type}>{issueLabels[report.issue_type] || 'Road issue'}</span></div>
        <p className="review-description">{report.description}</p><TrackingStatus report={report} /><button className="text-button" onClick={() => openReport(report.id)}>View report and progress →</button></article>)}</div>
      {!state.data.items.length && <div className="card workflow-record"><h2>No reports yet</h2><p>Your saved submissions will appear here.</p></div>}
      <Pager total={state.data.total} limit={20} offset={offset} onChange={setOffset} /></>}</Notice></>;
}
