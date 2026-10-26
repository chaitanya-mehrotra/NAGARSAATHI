import React, { useEffect, useRef, useState } from 'react';
import { photoBlob } from './services';

export function useRemote(load, dependencies, interval = 0) {
  const [state, setState] = useState({ data: null, error: '', loading: true, updated: null });
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true, timer;
    setState({ data: null, error: '', loading: true, updated: null });
    async function run() {
      try {
        const data = await load(controller.signal);
        if (active) setState({ data, error: '', loading: false, updated: new Date() });
      } catch (error) {
        if (active && error.name !== 'AbortError') setState({ data: null, error: error.message, loading: false, updated: null });
      } finally { if (active && interval) timer = setTimeout(run, interval); }
    }
    run();
    const resume = () => { clearTimeout(timer); if (!document.hidden) { controller.abort(); setRefresh(x => x + 1); } };
    document.addEventListener('visibilitychange', resume);
    return () => { active = false; controller.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', resume); };
  }, [...dependencies, refresh]);
  return { ...state, reload: () => setRefresh(x => x + 1) };
}
export function Notice({ state, children }) {
  if (state.loading) return <p className="workflow-notice" role="status">Loading saved records…</p>;
  if (state.error) return <div className="error-box" role="alert"><p>{state.error}</p><button className="secondary" onClick={state.reload}>Retry</button></div>;
  return children;
}
export function Photo({ path, alt = 'Reported road issue' }) {
  const [attempt, retry] = useState(0), [url, setUrl] = useState(''), [error, setError] = useState('');
  useEffect(() => {
    let active = true, objectUrl;
    const controller = new AbortController();
    setUrl(''); setError('');
    photoBlob(path, controller.signal).then(blob => {
      if (active) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); }
    }).catch(e => { if (active && e.name !== 'AbortError') setError(e.message); });
    return () => { active = false; controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path, attempt]);
  return error ? <div className="workflow-notice" role="status">{error} <button className="text-button" onClick={() => retry(x => x + 1)}>Retry photo</button></div>
    : url ? <img className="workflow-photo" src={url} alt={alt} /> : <p role="status">Loading photo…</p>;
}
export function Modal({ title, close, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    ref.current?.querySelector('button')?.focus();
    function keyboard(event) {
      if (event.key === 'Escape') close();
      if (event.key !== 'Tab') return;
      const elements = [...ref.current.querySelectorAll('button,input,select,textarea,a[href]')].filter(e => !e.disabled && e.getClientRects().length);
      const first = elements[0], last = elements.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener('keydown', keyboard);
    return () => { document.removeEventListener('keydown', keyboard); previous?.focus(); };
  }, [close]);
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && close()}><section ref={ref} className="details-drawer" role="dialog" aria-modal="true" aria-labelledby="detail-title">
    <button className="close secondary" aria-label="Close details" onClick={close}>Close</button>
    <h2 id="detail-title">{title}</h2>{children}
  </section></div>;
}
export function Pager({ total, offset, limit, onChange }) {
  return <div className="workflow-pager"><span>{total} saved records · Page {Math.floor(offset / limit) + 1}</span><div className="button-row">
    <button className="secondary" disabled={!offset} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</button>
    <button className="secondary" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next</button>
  </div></div>;
}
