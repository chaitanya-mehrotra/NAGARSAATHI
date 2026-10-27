import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MapPin, LayoutDashboard, Plus, FileText, ShieldCheck, Menu, ChevronRight, AlertCircle, Map as MapIcon } from 'lucide-react';
import { getStoredToken, identity, observeSessions, login, register, logout, request } from './services';
import { roleLabels, routeFromHash, roleCanOpen, locationLabel } from './workflows';
import { CitizenSubmit, CitizenReports, TrackingStatus } from './Citizen';
import { AdminInbox, IssueList, IssueDetail, Counts, Priority, ExceptionReview } from './Staff';
import { Modal, Notice, Photo, useRemote } from './ui';
import CityOverview from './CityOverview';
import { Archive, GoogleSignIn, ReportModeration } from './Collection';
import './style.css';
import './workflows.css';

function App() {
  const [session, setSession] = useState({ user: null, checking: true, error: '', generation: 0 });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true, controller, generation = 0;
    async function validate() {
      const current = ++generation;
      controller?.abort(); controller = new AbortController();
      setSession(s => ({ user: null, error: '', checking: !!getStoredToken(), generation: s.generation + 1 }));
      if (!getStoredToken()) return;
      try {
        const user = await identity(controller.signal);
        if (!roleLabels[user.role]) throw new Error('This account has no supported workspace. Contact your administrator.');
        if (active && current === generation) setSession(s => ({ ...s, user, checking: false }));
      } catch (e) {
        if (active && current === generation && e.name !== 'AbortError') setSession(s => ({ ...s, checking: false, error: e.message }));
      }
    }
    const stop = observeSessions(validate); validate();
    return () => { active = false; generation++; controller?.abort(); stop(); };
  }, [attempt]);
  if (session.checking) return <div className="workflow-gate"><div className="brand"><MapPin /> NAGARSAATHI</div><p role="status">Checking your session…</p></div>;
  if (!session.user) return <Workspace key={session.generation} user={null} authError={session.error} retrySession={() => setAttempt(x => x + 1)} />;
  return <Workspace key={session.generation} user={session.user} />;
}
function Auth({ error: sessionError, retry }) {
  const [mode, setMode] = useState('login'), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const controller = useRef(null), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort(); }; }, []);
  async function authenticate(event) {
    event.preventDefault(); if (busy) return;
    const data = new FormData(event.currentTarget); setBusy(true); setError(''); controller.current = new AbortController();
    try {
      if (mode === 'register') await register(data.get('name').trim(), data.get('email'), data.get('password'), controller.current.signal);
      await login(data.get('email'), data.get('password'), controller.current.signal);
    } catch (e) { if (mounted.current && e.name !== 'AbortError') setError(e.message); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <main className="workflow-auth"><section className="card workflow-form"><a className="brand" href="#"><span className="brand-symbol"><MapPin /></span><span>NAGARSAATHI<small>YOUR CITY. OUR RESPONSIBILITY.</small></span></a>
    <div className="eyebrow">YOUR NEIGHBOURHOOD, CONNECTED</div><h1>{mode === 'register' ? 'Create a citizen account' : 'Welcome back.'}</h1>
    <p className="muted">{mode === 'register' ? 'Report an issue and follow its progress.' : 'Citizens, platform administrators and Nagar Nigam staff sign in here.'}</p>
    {sessionError && <div className="error-box" role="alert"><p>{sessionError}</p><button className="secondary" onClick={retry}>Retry session</button><button className="text-button" onClick={logout}>Use another account</button></div>}
    <form onSubmit={authenticate}>{mode === 'register' && <><label htmlFor="name">Full name</label><input id="name" name="name" maxLength={100} required autoComplete="name" /></>}
      <label htmlFor="email">Email address</label><input id="email" name="email" type="email" required maxLength={254} autoComplete="username" />
      <label htmlFor="password">Password</label><input id="password" name="password" type="password" required minLength={mode === 'register' ? 10 : 1} maxLength={128} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} />
      {error && <div className="error-box" role="alert">{error}</div>}<button className="primary" disabled={busy}>{busy ? 'Please wait…' : mode === 'register' ? 'Create citizen account' : 'Sign in'}</button>
    </form><button className="text-button" disabled={busy} onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>{mode === 'login' ? 'New here? Register as a citizen' : 'Already registered? Sign in'}</button>
    <GoogleSignIn /><p className="muted">Staff accounts are created by the platform administrator. Public registration creates citizen accounts only.</p>
  </section></main>;
}
const navigation = {
  citizen: [['Overview', LayoutDashboard], ['Report Issue', Plus], ['Complaint Map', MapIcon], ['My Reports', FileText]],
  admin: [['All submissions', LayoutDashboard], ['Overview', MapIcon], ['Exceptions', AlertCircle], ['Shared issues', FileText], ['Archived reports', ShieldCheck]],
  nigam: [['Published issues', LayoutDashboard]],
};
function Workspace({ user, authError = '', retrySession }) {
  const role = user?.role || 'citizen';
  const [authOpen, setAuthOpen] = useState(!!authError);
  const closeAuth = useCallback(() => setAuthOpen(false), []);
  const [page, setPage] = useState(navigation[role][0][0]), [mobile, setMobile] = useState(false), [route, setRoute] = useState(() => routeFromHash(location.hash));
  useEffect(() => { const changed = () => setRoute(routeFromHash(location.hash)); window.addEventListener('hashchange', changed); return () => window.removeEventListener('hashchange', changed); }, []);
  const close = useCallback(() => { history.replaceState(null, '', location.pathname + location.search); setRoute(null); }, []);
  function open(kind, id) { location.hash = `/${kind}/${id}`; setRoute({ kind, id: String(id) }); }
  const openReport = id => open('reports', id), openIssue = id => open('issues', id);
  return <div className="app"><aside className={'sidebar ' + (mobile ? 'open' : '')}><a href="#" className="brand" onClick={e => { e.preventDefault(); close(); setPage(navigation[role][0][0]); }}><span className="brand-symbol"><MapPin size={24} /></span><span>NAGARSAATHI<small>YOUR CITY. OUR RESPONSIBILITY.</small></span></a>
    <div className="workspace-label">{roleLabels[role].toUpperCase()}</div><nav aria-label="Workspace navigation">{navigation[role].map(([label, Icon]) => <button className={'nav-item ' + (page === label ? 'active' : '')} key={label} onClick={() => { if (!user && label !== 'Overview' && label !== 'Complaint Map') { setAuthOpen(true); setMobile(false); return; } setPage(label); setMobile(false); close(); }}><Icon size={19} />{label}{page === label && <span className="active-dot" />}</button>)}</nav>
    <div className="sidebar-bottom"><div className="together"><span className="mini-icon"><ShieldCheck /></span><h3>Small reports.<br />Better neighbourhoods.</h3><p>Stay connected from the first report to the final repair.</p></div><div className="session"><span className="avatar">{user?.name?.[0]?.toUpperCase() || 'N'}</span><div><strong>{user?.name || 'Your citizen account'}</strong><small>{roleLabels[role]}</small></div></div></div></aside>
    <div className="main"><header className="topbar"><button className="mobile-menu icon-button" aria-label="Toggle navigation" aria-expanded={mobile} onClick={() => setMobile(!mobile)}><Menu /></button><div className="breadcrumb">Workspace <ChevronRight size={14} /><strong>{page}</strong></div><div className="top-actions">{user ? <button className="secondary" onClick={logout}>Sign out</button> : <button className="secondary" onClick={() => setAuthOpen(true)}>Sign in</button>}{role === 'citizen' && <button className="primary" onClick={() => user ? setPage('Report Issue') : setAuthOpen(true)}><Plus size={17} />Report Issue</button>}</div></header>
      <main><div className="page-heading"><div className="eyebrow">{roleLabels[role].toUpperCase()}</div><h1>{page === 'Overview' ? 'Your city, at a glance.' : page === 'Complaint Map' ? 'Every report. On the map.' : page === 'My Reports' ? 'Your voice. A better city.' : page === 'Report Issue' ? 'Report an issue' : page}</h1><p>{role === 'citizen' ? 'A photo, a pin, and a few details can make a difference.' : 'Clear evidence. Shared action. Visible progress.'}</p></div>
        {(page === 'Overview' || page === 'Complaint Map') && <CityOverview key={page} user={user} mapOnly={page === 'Complaint Map'} openReport={openReport} report={() => setPage(role === 'admin' ? 'All submissions' : 'Report Issue')} signIn={() => setAuthOpen(true)} />}
        {role === 'citizen' && page === 'Report Issue' && user && <CitizenSubmit openReport={openReport} />}
        {role === 'citizen' && page === 'My Reports' && user && <CitizenReports openReport={openReport} />}
        {role === 'admin' && page !== 'Overview' && (page === 'Archived reports' ? <Archive openReport={openReport} /> : page === 'Shared issues' ? <IssueList role="admin" openIssue={openIssue} /> : <AdminInbox key={page} exceptions={page === 'Exceptions'} openReport={openReport} openIssue={openIssue} />)}
        {role === 'nigam' && <IssueList role="nigam" openIssue={openIssue} />}
      </main><footer className="workflow-footer">NAGARSAATHI · Your city. Our responsibility.</footer></div>
    {authOpen && <Modal title="Sign in to NAGARSAATHI" close={closeAuth}><Auth error={authError} retry={retrySession || (() => {})} /></Modal>}
    {route && user && <Modal title={`${route.kind === 'issues' ? 'Issue' : 'Report'} #${route.id}`} close={close}>
      {!roleCanOpen(role, route) ? <p role="alert">This record is not available in your workspace.</p> : route.kind === 'issues' ? <IssueDetail id={route.id} role={role} /> : <ReportDetail id={route.id} role={role} openIssue={openIssue} />}
    </Modal>}
  </div>;
}
function ReportDetail({ id, role, openIssue }) {
  const state = useRemote(signal => request(`/reports/${id}`, { signal }), [id], 15000);
  return <Notice state={state}>{state.data && <><Photo path={`/reports/${id}/photo`} /><p className="review-description">{state.data.description}</p><p>Location: {locationLabel(state.data)}</p><TrackingStatus report={state.data} />
    {role === 'admin' && <section className="workflow-admin-detail"><h3>Processing and grouping</h3><p>Processing: {state.data.processing_status || 'Not supplied'}</p>
      {state.data.exception_reason && <div className="workflow-exception">{state.data.exception_reason}</div>}
      {state.data.issue_id != null && <button className="text-button" onClick={() => openIssue(state.data.issue_id)}>Shared issue #{state.data.issue_id} →</button>}
      <p>{state.data.grouping_reason || 'Grouping explanation not supplied yet.'}</p>{state.data.issue && <><Counts item={state.data.issue} /><Priority item={state.data.issue} /></>}
      {state.data.needs_attention && !state.data.archived_at && <ExceptionReview key={id} report={state.data} reload={state.reload} />}<ReportModeration report={state.data} reload={state.reload} /></section>}
  </>}</Notice>;
}
createRoot(document.getElementById('root')).render(<App />);
