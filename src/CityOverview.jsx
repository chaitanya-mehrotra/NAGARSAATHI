import React, { useState } from 'react';
import { Map as MapIcon, MapPin, FileText, Construction, Droplets, CheckCheck, ArrowUpRight, ArrowRight, Search, RefreshCw, Clock, ShieldCheck } from 'lucide-react';
import ComplaintMap from './Map';
import { request } from './services';
import { issueLabels } from './validation';
import { pageOf, repairLabels, verificationLabels } from './workflows';
import { Notice, Pager, useRemote } from './ui';

// Chaitanya's original map/list dashboard. Every total is requested from the API;
// the frontend never counts, groups or ranks the reports on the current page.
export default function CityOverview({ user, openReport, report, signIn, mapOnly = false }) {
  const [search, setSearch] = useState(''), [issue, setIssue] = useState(''), [status, setStatus] = useState('');
  const [offset, setOffset] = useState(0), [view, setView] = useState('map'), [selected, setSelected] = useState(null);
  const scope = user?.role === 'admin' ? '' : '&mine=true';
  const params = new URLSearchParams({ search, issue, status, limit: '20', offset: String(offset) });
  const state = useRemote(signal => user ? request(`/complaints?${params}${scope}`, { signal }).then(pageOf) : Promise.resolve(null), [user?.id, search, issue, status, offset], user ? 15000 : 0);
  const summary = useRemote(async signal => {
    if (!user) return null;
    const counts = await Promise.all(['', '&issue=pothole', '&issue=waterlogging', '&status=resolved'].map(filter =>
      request(`/complaints?limit=1&offset=0${scope}${filter}`, { signal }).then(pageOf)));
    return counts.map(result => result.total);
  }, [user?.id], user ? 15000 : 0);
  const cards = [['Total complaints', 'All saved reports', FileText, ''], ['Pothole reports', 'Road surface issues', Construction, 'pothole'],
    ['Waterlogging reports', 'Drainage & flooding', Droplets, 'waterlogging'], ['Resolved complaints', 'Issues taken care of', CheckCheck, 'resolved']];
  const rows = state.data?.items || [];
  // Invalid coordinates should not crash the map. No complaint is removed from the list.
  const mapRows = rows.filter(r => Number.isFinite(r.latitude) && Number.isFinite(r.longitude) && Math.abs(r.latitude) <= 90 && Math.abs(r.longitude) <= 180);
  function filter(field, value) { setOffset(0); setSelected(null); if (field === 'search') setSearch(value); else if (field === 'issue') setIssue(value); else setStatus(value); }
  return <>
    {!user && <div className="setup-banner"><span className="setup-icon"><ShieldCheck size={19} /></span><div><strong>Your city. Your voice. One place to make a difference.</strong>
      <p>Sign in to submit an issue and follow your saved reports.</p></div><button onClick={signIn}>Sign in to get started <ArrowUpRight size={16} /></button></div>}
    {!mapOnly && <div className="metrics">{cards.map(([title, sub, Icon, value], i) => <button key={title} className={'metric card ' + value} onClick={() => {
      setOffset(0); setIssue(value === 'resolved' ? '' : value); setStatus(value === 'resolved' ? 'resolved' : '');
    }}><div className="metric-top"><span className="metric-icon"><Icon size={21} /></span><ArrowUpRight size={16} /></div><span className="metric-label">{title}</span>
      <strong>{summary.data ? summary.data[i] : user && summary.loading ? '…' : '—'}</strong><small>{user ? sub : 'Sign in to view your reports'}</small></button>)}</div>}
    {summary.error && <div className="workflow-notice" role="status">Summary totals are unavailable. <button className="text-button" onClick={summary.reload}>Retry totals</button></div>}
    <section className="card workspace"><div className="workspace-header"><div><div className="panel-title"><span className="section-icon"><MapIcon size={19} /></span>
      <h2>{user?.role === 'admin' ? 'Neighbourhood reports' : 'Your neighbourhood reports'}</h2><span className="outline-badge">{state.data ? `${state.data.total} complaints` : user ? 'Loading' : 'Sign in required'}</span></div>
      <p>{user ? 'Your saved reports, their locations and their next steps.' : 'A clearer picture of your neighbourhood starts with you.'}</p></div>
      <button className="text-button refresh" disabled={!user || state.loading} onClick={() => { state.reload(); summary.reload(); }} aria-label="Refresh reports"><RefreshCw size={15} />Refresh</button></div>
      <div className="filter-bar"><div className="search-box"><Search size={17} /><input aria-label="Search complaints" placeholder="Search by reference or description…" value={search} onChange={e => filter('search', e.target.value)} disabled={!user} /></div>
        <select aria-label="Issue type filter" value={issue} onChange={e => filter('issue', e.target.value)} disabled={!user}><option value="">All issue types</option>{Object.entries(issueLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select>
        <select aria-label="Status filter" value={status} onChange={e => filter('status', e.target.value)} disabled={!user}><option value="">All repair statuses</option>{Object.entries(repairLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select>
        {(search || issue || status) && <button className="text-button" onClick={() => { setSearch(''); setIssue(''); setStatus(''); setOffset(0); }}>Clear filters</button>}</div>
      <div className="mobile-switch"><button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}><MapIcon size={16} />Map</button><button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}><FileText size={16} />List</button></div>
      {state.error && <Notice state={state} />}
      <div className={'map-list view-' + view}><div className="main-map"><ComplaintMap rows={mapRows} selected={selected} onSelect={setSelected} onDetails={openReport ? row => openReport(row.id) : undefined} />
        <div className="map-caption"><span><span className="dot neutral" />{user ? 'Saved complaint locations · refreshes every 15 seconds' : 'Sign in to see your saved locations'}</span><small>Location is never continuously tracked.</small></div></div>
        <div className="complaint-list"><div className="list-heading"><h3>{user?.role === 'admin' ? 'Recent complaints' : 'Your complaints'}</h3></div>
          {state.loading && user ? <div className="skeletons" role="status" aria-label="Loading complaints">{[1,2,3].map(n => <div className="skeleton" key={n} />)}</div> : rows.length ? rows.map(row =>
            <button key={row.id} className={'complaint-row ' + (selected?.id === row.id ? 'selected' : '')} onClick={() => { setSelected(mapRows.find(r => r.id === row.id) || null); openReport(row.id); }}>
              <div className="complaint-row-top"><span className={'badge ' + row.issue_type}>{issueLabels[row.issue_type] || 'Road issue'}</span><small>{row.reference || `#${row.id}`}</small></div>
              <h3>{row.reference || `Report #${row.id}`}</h3><h4>{row.description}</h4><span className="reference">{verificationLabels[row.verification_status] || 'Verification pending'}</span>
              <div className="complaint-row-bottom"><span className={'status ' + row.status}><i />{repairLabels[row.status] || 'Awaiting an update'}</span><ArrowUpRight size={16} /></div></button>)
            : <div className="list-empty"><span className="empty-art"><MapPin size={31} /></span><h3>{user ? 'No reports here yet' : 'A fresh start for your city'}</h3>
              <p>{user ? 'Try another filter or put an issue on the map.' : 'Sign in to view your saved complaints or report an issue on your street.'}</p><button className="secondary" onClick={user ? report : signIn}>{user?.role === 'admin' ? 'Review submissions' : user ? 'Report an issue' : 'View your reports'}</button></div>}
        </div></div>{state.data && <div className="city-pagination"><Pager total={state.data.total} offset={offset} limit={20} onChange={setOffset} /></div>}</section>
    {!mapOnly && <div className="bottom-grid"><section className="card status-card"><div className="panel-title"><Clock size={18} /><h3>From reported to resolved</h3></div><p>Every report has a next step.</p>
      <div className="city-stages">{['Awaiting verification', 'Reviewed for action', 'Repair progress'].map((label, i) => <div key={label}><span>{i + 1}</span><strong>{label}</strong></div>)}</div></section>
      <section className="community-card"><span className="community-icon"><Construction size={28} /></span><div><span className="eyebrow">A LITTLE ACTION GOES A LONG WAY</span><h3>Spotted an issue on your street?</h3><p>Help put it on the map. It only takes a few minutes.</p><button className="text-button" onClick={user ? report : signIn}>{user?.role === 'admin' ? 'Review submissions' : 'Create a report'} <ArrowRight size={16} /></button></div></section></div>}
  </>;
}
