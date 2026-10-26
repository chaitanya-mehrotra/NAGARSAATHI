import React, { useState } from "react";
import { request } from "./services";

export function IssueCounts({ issue }) {
  if (!issue) return null;
  return <div className="privacy-note" style={{ margin: "12px 0" }}>
    <span><strong>Issue #{issue.id}</strong> · {issue.report_count} reports from {issue.reporter_count} distinct accounts
      {issue.unique_photo_count != null && <> · {issue.unique_photo_count} unique photos</>}
    </span>
  </div>;
}

export function GroupingControls({ report, onChanged }) {
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function change(path, body) {
    setBusy(true); setError("");
    try {
      await request(path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const updated = await request(`/reports/${report.id}`);
      onChanged(updated);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  const issue = report.issue_summary;
  if (!issue) return null;
  return <section className="ai-panel" aria-label="Duplicate grouping">
    <strong>Duplicate grouping — platform admin</strong>
    <p>Keep every report here. Nagar Nigam receives one consolidated issue with the counts above.</p>
    <p>{issue.published ? "Visible to Nagar Nigam" : "Not yet sent to Nagar Nigam"}</p>
    <button className="secondary" disabled={busy}
      onClick={() => change(`/issues/${issue.id}/publication`, { published: !issue.published })}>
      {issue.published ? "Withdraw from Nagar Nigam" : "Send consolidated issue to Nagar Nigam"}
    </button>
    {(report.duplicate_candidates || []).length > 0 && <>
      <p>Possible matches — review the photos and location before grouping:</p>
      {report.duplicate_candidates.map(c => <p key={c.issue_id}>
        <button className="secondary" onClick={() => setTarget(String(c.issue_id))} disabled={busy}>
          Select Issue #{c.issue_id}
        </button> {c.reason === "reused_photo_different_location" ? "Same photo at a different location — check for reused evidence"
          : c.reason === "legacy_distance_only" ? "Old distance-only suggestion — needs review"
          : c.reason === "nearby_similar_photo" ? "Nearby, similar-looking photo" : "Nearby, same category"}
        {c.issue && <> · {c.issue.report_count} reports · {c.issue.description}</>}
      </p>)}
    </>}
    <label>Existing issue ID to attach this report to
      <input type="number" min="1" value={target} onChange={e => setTarget(e.target.value)} />
    </label>
    <label>Grouping / separation reason
      <input maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} placeholder="Explain why these reports concern the same or different issue" />
    </label>
    <div className="button-row">
      <button className="secondary" disabled={busy || !reason.trim() || !Number.isInteger(Number(target)) || Number(target) < 1}
        onClick={() => change(`/issues/report/${report.id}/group`, { issue_id: Number(target), reason })}>
        Attach report to selected issue
      </button>
      <button className="secondary" disabled={busy || !reason.trim() || issue.report_count < 2}
        onClick={() => change(`/issues/report/${report.id}/group`, { issue_id: null, reason })}>
        Separate this report into a new issue
      </button>
    </div>
    {error && <p role="alert">{error}</p>}
  </section>;
}
