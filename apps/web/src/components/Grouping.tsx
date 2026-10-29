import React, { useState } from "react";

export interface IssueSummaryData {
  id: string | number;
  report_count: number;
  reporter_count: number;
  unique_photo_count?: number | null;
  published?: boolean;
  description?: string;
}

export interface DuplicateCandidate {
  issue_id: string | number;
  reason: string;
  issue?: {
    report_count: number;
    description: string;
  };
}

export interface ReportWithIssue {
  id: string | number;
  issue_summary?: IssueSummaryData | null;
  duplicate_candidates?: DuplicateCandidate[];
}

export function IssueCounts({ issue }: { issue?: IssueSummaryData | null }) {
  if (!issue) return null;
  return (
    <div className="privacy-note" style={{ margin: "12px 0" }}>
      <span>
        <strong>Issue #{issue.id}</strong> · {issue.report_count} reports from {issue.reporter_count} distinct accounts
        {issue.unique_photo_count != null && <> · {issue.unique_photo_count} unique photos</>}
      </span>
    </div>
  );
}

export function GroupingControls({
  report,
  onChanged,
  apiRequest,
}: {
  report: ReportWithIssue;
  onChanged?: (updated: any) => void;
  apiRequest: (path: string, options?: RequestInit) => Promise<any>;
}) {
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleAction(path: string, body: any) {
    setBusy(true);
    setError("");
    try {
      await apiRequest(path, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const updated = await apiRequest(`/api/v1/reports/${report.id}`);
      onChanged?.(updated);
    } catch (e: any) {
      setError(e.message || "Failed to update grouping");
    } finally {
      setBusy(false);
    }
  }

  const issue = report.issue_summary;
  if (!issue) return null;

  return (
    <section className="ai-panel" aria-label="Duplicate grouping">
      <strong>Duplicate Grouping — Platform Moderation</strong>
      <p>Retain distinct citizen reports. Municipal staff receives one consolidated issue with aggregated counts.</p>
      <p>{issue.published ? "Visible to Nagar Nigam" : "Not yet sent to Nagar Nigam"}</p>
      <button
        className="secondary"
        disabled={busy}
        onClick={() => handleAction(`/api/v1/issues/${issue.id}/publication`, { published: !issue.published })}
      >
        {issue.published ? "Withdraw from Nagar Nigam" : "Send consolidated issue to Nagar Nigam"}
      </button>

      {(report.duplicate_candidates || []).length > 0 && (
        <>
          <p style={{ marginTop: "12px" }}>Possible matches — review photos and coordinates before grouping:</p>
          {report.duplicate_candidates?.map((candidate) => (
            <div key={candidate.issue_id} style={{ margin: "6px 0" }}>
              <button
                className="secondary"
                style={{ marginRight: "8px", fontSize: "12px" }}
                onClick={() => setTarget(String(candidate.issue_id))}
                disabled={busy}
              >
                Select Issue #{candidate.issue_id}
              </button>
              <span>
                {candidate.reason === "reused_photo_different_location"
                  ? "Same photo at a different location — check for reused evidence"
                  : candidate.reason === "legacy_distance_only"
                  ? "Old distance-only suggestion — needs review"
                  : candidate.reason === "nearby_similar_photo"
                  ? "Nearby, similar-looking photo"
                  : "Nearby, same category"}
              </span>
              {candidate.issue && (
                <span> · {candidate.issue.report_count} reports · {candidate.issue.description}</span>
              )}
            </div>
          ))}
        </>
      )}

      <div style={{ marginTop: "14px" }}>
        <label style={{ display: "block", marginBottom: "6px" }}>
          Target Issue ID to link this report to
          <input
            type="number"
            min="1"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            style={{ display: "block", width: "100%", marginTop: "4px" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "6px" }}>
          Grouping / Separation Reason
          <input
            maxLength={1000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Explain why these reports concern the same or different physical issue"
            style={{ display: "block", width: "100%", marginTop: "4px" }}
          />
        </label>
        <div className="button-row" style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
          <button
            className="secondary"
            disabled={busy || !reason.trim() || !Number.isInteger(Number(target)) || Number(target) < 1}
            onClick={() => handleAction(`/api/v1/issues/report/${report.id}/group`, { issue_id: Number(target), reason })}
          >
            Attach report to selected issue
          </button>
          <button
            className="secondary"
            disabled={busy || !reason.trim() || (issue.report_count || 0) < 2}
            onClick={() => handleAction(`/api/v1/issues/report/${report.id}/group`, { issue_id: null, reason })}
          >
            Separate into new issue
          </button>
        </div>

        {/* Deduplication: Delete all duplicates and keep only 1 */}
        <div style={{ marginTop: "16px", paddingTop: "12px", borderTop: "1px dashed var(--border)" }}>
          <strong style={{ display: "block", color: "#dc2626", marginBottom: "4px" }}>
            Resolve Duplicates (Keep Only 1)
          </strong>
          <p style={{ fontSize: "12px", color: "var(--muted)", margin: "0 0 8px" }}>
            Permanently resolve and soft-delete all other duplicate complaints associated with this issue, keeping only this primary complaint.
          </p>
          <button
            type="button"
            className="secondary"
            style={{
              background: "#fee2e2",
              borderColor: "#fca5a5",
              color: "#991b1b",
              fontWeight: 600,
            }}
            disabled={busy}
            onClick={async () => {
              if (window.confirm(`Delete all duplicate complaints linked to this issue and keep only report #${report.id}?`)) {
                setBusy(true);
                try {
                  const res = await apiRequest(`/api/v1/reports/${report.id}/deduplicate-keep-one`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ reason: reason || "Deduplication: removed duplicate reports, retaining primary complaint" }),
                  });
                  alert(res.message || "Duplicates successfully deleted.");
                  const updated = await apiRequest(`/api/v1/reports/${report.id}`);
                  onChanged?.(updated);
                } catch (e: any) {
                  setError(e.message || "Failed to deduplicate");
                } finally {
                  setBusy(false);
                }
              }
            }}
          >
            Delete all duplicates (keep this report)
          </button>
        </div>
      </div>
      {error && <p role="alert" style={{ color: "#dc2626", marginTop: "8px" }}>{error}</p>}
    </section>
  );
}
