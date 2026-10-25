import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";
import {
  api,
  type ReportDetail,
  type IssueSummary,
  type IssueDetail,
  type DuplicateReview,
} from "../api/client";
import { SignIn, useSession } from "../session";
import { PrivatePhoto } from "./citizen";
import { PriorityReview } from "./priority";
import { AssignmentPanel } from "./staff";
import { WorkPanel } from "./work";

function Evidence({ report }: { report: ReportDetail }) {
  return (
    <article>
      <h3>{report.description}</h3>
      {report.reported_hazard && (
        <p className="notice">
          Immediate hazard reported — staff confirmation pending.
        </p>
      )}
      <p>
        {report.public_reference} · {report.canonical_category} ·{" "}
        {report.area_code}
      </p>
      <p>
        Received {new Date(report.received_at).toLocaleString("en-IN")} ·
        Evidence revision {report.content_revision}
      </p>
      <p>
        Pin: {report.canonical_location?.longitude},{" "}
        {report.canonical_location?.latitude}. Trusted asset:{" "}
        {report.trusted_asset_id || "None"}.
      </p>
      {report.evidence_reused && (
        <p className="notice">
          This photo was used in another report. Review whether it is
          independent evidence.
        </p>
      )}
      <div className="photo-grid">
        {report.media.map((m, i) => (
          <PrivatePhoto
            key={m.id}
            url={m.content_url}
            alt={`Comparison evidence ${i + 1}`}
          />
        ))}
      </div>
    </article>
  );
}

function CandidateEvidence({ id }: { id: string }) {
  const { token } = useSession();
  const detail = useQuery({
    queryKey: ["candidate-evidence", id],
    queryFn: () => api<IssueDetail>(`/api/v1/issues/${id}`, token),
  });
  return (
    <>
      {detail.isPending && <p role="status">Loading existing evidence…</p>}
      {detail.isError && <p role="alert">{detail.error.message}</p>}
      {detail.data?.reports.slice(0, 3).map((r) => (
        <Evidence key={r.id} report={r} />
      ))}
    </>
  );
}

export function Duplicates() {
  const { actor, token } = useSession();
  const records = useQuery({
    queryKey: ["duplicates", actor?.id],
    enabled: !!actor,
    queryFn: () => api<DuplicateReview[]>("/api/v1/reviews/duplicates", token),
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>Duplicate review</h1>
      <p>
        Compare the physical defect, pin and evidence before linking. Proximity
        alone is a suggestion.
      </p>
      <button className="secondary" onClick={() => void records.refetch()}>
        Reload candidates
      </button>
      {records.isPending && <p role="status">Loading candidates…</p>}
      {records.isError && <p role="alert">{records.error.message}</p>}
      {records.data?.length === 0 && <p>No pending duplicate decisions.</p>}
      {records.data?.map((record) => (
        <DuplicateDecision
          key={`${record.report.id}:${record.report.content_revision}`}
          record={record}
          refresh={() => void records.refetch()}
        />
      ))}
    </section>
  );
}

function DuplicateDecision({
  record,
  refresh,
}: {
  record: DuplicateReview;
  refresh: () => void;
}) {
  const { token } = useSession();
  const [selected, setSelected] = useState("");
  const [reason, setReason] = useState("");
  const [independent, setIndependent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(crypto.randomUUID());
  const candidate = record.candidates.find((c) => c.issue.id === selected);
  async function decide(action: string) {
    if (busy) return;
    if (reason.trim().length < 5) {
      setError("Record a reason of at least five characters.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(
        `/api/v1/reviews/duplicates/${record.report.id}/decision`,
        token,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            request_id: request.current,
            expected_revision: record.report.content_revision,
            action,
            issue_id: ["link", "recurrence"].includes(action)
              ? candidate?.issue.id
              : null,
            expected_issue_version: candidate?.issue_revision || null,
            reason,
            independent_evidence: independent,
          }),
        },
      );
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="duplicate-card">
      <div className="comparison-grid">
        <Evidence report={record.report} />
        <div>
          <label htmlFor={`candidate-${record.report.id}`}>
            Existing issue candidate
          </label>
          <select
            id={`candidate-${record.report.id}`}
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              request.current = crypto.randomUUID();
            }}
          >
            <option value="">Choose a candidate</option>
            {record.candidates.map((c) => (
              <option key={c.id} value={c.issue.id}>
                {c.issue.public_reference} · {c.distance_m.toFixed(1)} m ·{" "}
                {c.issue.status}
                {c.asset_conflict ? " · asset conflict" : ""}
              </option>
            ))}
          </select>
          {candidate && (
            <>
              <p>
                {candidate.kind} · area {candidate.issue.area_code} · issue
                version {candidate.issue_revision} ·{" "}
                {candidate.issue.report_count} reports
              </p>
              <Link to={`/issues/${candidate.issue.id}`}>
                View shared issue and history
              </Link>
              <CandidateEvidence id={candidate.issue.id} />
            </>
          )}
          {record.needs_cross_area_admin && (
            <p className="notice">
              A candidate belongs to another area. A reviewer with access to
              both areas must decide.
            </p>
          )}
        </div>
      </div>
      <form
        onSubmit={(e) => e.preventDefault()}
        onChange={() => {
          request.current = crypto.randomUUID();
        }}
      >
        <fieldset disabled={busy}>
          <legend>Physical issue decision</legend>
          <label htmlFor={`duplicate-reason-${record.report.id}`}>
            Comparison reason
          </label>
          <textarea
            id={`duplicate-reason-${record.report.id}`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {record.report.evidence_reused && (
            <label>
              <input
                type="checkbox"
                checked={independent}
                onChange={(e) => setIndependent(e.target.checked)}
              />{" "}
              I reviewed and confirmed independent evidence
            </label>
          )}
          <div className="actions">
            <button
              type="button"
              disabled={
                !candidate ||
                candidate.asset_conflict ||
                candidate.issue.status === "resolved"
              }
              onClick={() => void decide("link")}
            >
              Link to existing issue
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => void decide("new")}
            >
              Create separate issue
            </button>
            <button
              type="button"
              className="secondary"
              disabled={
                !candidate ||
                candidate.asset_conflict ||
                candidate.issue.status !== "resolved"
              }
              onClick={() => void decide("recurrence")}
            >
              Record recurrence
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => void decide("clarify")}
            >
              Request clarification
            </button>
          </div>
        </fieldset>
      </form>
      {error && (
        <p role="alert">
          {error} Reload candidates before retrying a changed record.
        </p>
      )}
    </article>
  );
}

export function Issues() {
  const { actor, token } = useSession();
  const [cursor, setCursor] = useState("");
  const records = useQuery({
    queryKey: ["issues", actor?.id, cursor],
    enabled: !!actor,
    queryFn: () =>
      api<IssueSummary[]>(
        `/api/v1/issues${cursor ? `?cursor=${cursor}` : ""}`,
        token,
      ),
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>Shared issues</h1>
      <Link to="/reviews/duplicates">Review potential duplicates</Link>
      {records.isPending && <p role="status">Loading issues…</p>}
      {records.isError && <p role="alert">{records.error.message}</p>}
      <ul className="report-list">
        {records.data?.map((r) => (
          <li key={r.id}>
            <Link to={`/issues/${r.id}`}>
              <strong>
                {r.category.replaceAll("_", " ")} · {r.area_code}
              </strong>
              <span>
                {r.status} · {r.report_count} reports ·{" "}
                {r.eligible_reporter_count} eligible reporters
              </span>
              <small>{r.public_reference}</small>
            </Link>
          </li>
        ))}
      </ul>
      {records.data?.length === 20 && (
        <button onClick={() => setCursor(records.data?.at(-1)?.id || "")}>
          More issues
        </button>
      )}
      {cursor && <button onClick={() => setCursor("")}>First page</button>}
    </section>
  );
}

export function SharedIssue() {
  const [search] = useSearchParams();
  const returnTo = search.get("returnTo");
  const { actor, token } = useSession();
  const { id } = useParams();
  const detail = useQuery({
    queryKey: ["issue", actor?.id, id],
    enabled: !!actor,
    queryFn: () => api<IssueDetail>(`/api/v1/issues/${id}`, token),
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>Shared issue</h1>
      <Link to="/issues">All issues</Link>
      {returnTo && /^\/staff(?:\?|$)/.test(returnTo) && (
        <Link to={returnTo}>Back to work queue</Link>
      )}
      <button className="secondary" onClick={() => void detail.refetch()}>
        Reload issue
      </button>
      {detail.isPending && <p role="status">Loading issue…</p>}
      {detail.isError && <p role="alert">{detail.error.message}</p>}
      {detail.data && (
        <>
          <WorkPanel
            key={`work:${detail.data.row_version}`}
            id={detail.data.id}
          />
          <AssignmentPanel
            key={`assign:${id}:${detail.data.row_version}`}
            issue={detail.data}
            refresh={() => void detail.refetch()}
          />
          <IssueActions
            key={`${id}:${detail.data.row_version}`}
            issue={detail.data}
            refresh={() => void detail.refetch()}
          />
        </>
      )}
    </section>
  );
}

function IssueActions({
  issue,
  refresh,
}: {
  issue: IssueDetail;
  refresh: () => void;
}) {
  const { token } = useSession();
  const [target, setTarget] = useState("");
  const [targetReference, setTargetReference] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [lon, setLon] = useState(String(issue.point.longitude));
  const [lat, setLat] = useState(String(issue.point.latitude));
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef(crypto.randomUUID());
  const options = useQuery({
    queryKey: ["merge-options", issue.id, targetReference],
    queryFn: () =>
      api<IssueSummary[]>(
        `/api/v1/issues?limit=50${targetReference ? `&reference=${encodeURIComponent(targetReference.trim())}` : ""}`,
        token,
      ),
  });
  async function save(action: "merge" | "split") {
    if (busy) return;
    if (reason.trim().length < 5) {
      setError("Record a reason of at least five characters.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const selected = options.data?.find((i) => i.id === target);
      const payload =
        action === "merge"
          ? {
              target_id: target,
              expected_target_version: selected?.row_version,
            }
          : {
              report_ids: chosen,
              point: {
                longitude: Number(lon),
                latitude: Number(lat),
                confirmed: true,
              },
            };
      const result = await api<IssueSummary>(
        `/api/v1/issues/${issue.id}/${action}`,
        token,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...payload,
            expected_version: issue.row_version,
            request_id: request.current,
            reason,
          }),
        },
      );
      setError(`Saved ${action}. Result: ${result.public_reference}`);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <p className="tracking">{issue.public_reference}</p>
      <p>
        {issue.category} · {issue.area_code} · {issue.status} · version{" "}
        {issue.row_version}
      </p>
      <p>
        {issue.report_count} linked reports · {issue.eligible_reporter_count}{" "}
        eligible reporters.
      </p>
      {issue.merged_into_id && (
        <Link to={`/issues/${issue.merged_into_id}`}>Open surviving issue</Link>
      )}
      {issue.recurrence_parent_id && (
        <Link to={`/issues/${issue.recurrence_parent_id}`}>
          Open resolved predecessor
        </Link>
      )}
      <PriorityReview issue={issue} refresh={refresh} />
      <h2>Linked evidence</h2>
      {issue.reports.map((r) => (
        <div key={r.id}>
          <Evidence report={r} />
          <label className="split-selection">
            <input
              type="checkbox"
              checked={chosen.includes(r.id)}
              onChange={(e) => {
                setChosen((old) =>
                  e.target.checked
                    ? [...old, r.id]
                    : old.filter((x) => x !== r.id),
                );
                request.current = crypto.randomUUID();
              }}
            />{" "}
            Select for split
          </label>
          <Link to={`/reviews/${r.id}`}>Review or reclassify report</Link>
        </div>
      ))}
      {!issue.merged_into_id && (
        <form
          onSubmit={(e) => e.preventDefault()}
          onChange={() => {
            request.current = crypto.randomUUID();
          }}
        >
          <fieldset disabled={busy}>
            <legend>Merge or split after reviewing evidence</legend>
            <label htmlFor="merge-reference">
              Find merge target by exact issue reference
            </label>
            <input
              id="merge-reference"
              maxLength={128}
              value={targetReference}
              onChange={(e) => {
                setTargetReference(e.target.value);
                setTarget("");
              }}
            />
            <p className="hint">
              Use the issue reference to find a target beyond the first 50
              results.
            </p>
            <label htmlFor="merge-target">Merge into existing issue</label>
            <select
              id="merge-target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">Choose a surviving issue</option>
              {options.data
                ?.filter(
                  (r) =>
                    r.id !== issue.id &&
                    r.category === issue.category &&
                    !["merged", "resolved", "rejected"].includes(r.status),
                )
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.public_reference} · {r.area_code} · version{" "}
                    {r.row_version}
                  </option>
                ))}
            </select>
            {options.isError && <p role="alert">{options.error.message}</p>}
            <div className="form-grid">
              <div>
                <label htmlFor="split-lon">Split longitude</label>
                <input
                  id="split-lon"
                  type="number"
                  step="any"
                  value={lon}
                  onChange={(e) => setLon(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="split-lat">Split latitude</label>
                <input
                  id="split-lat"
                  type="number"
                  step="any"
                  value={lat}
                  onChange={(e) => setLat(e.target.value)}
                />
              </div>
            </div>
            <label htmlFor="issue-reason">Change reason</label>
            <textarea
              id="issue-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <div className="actions">
              <button
                type="button"
                disabled={!target}
                onClick={() => void save("merge")}
              >
                Merge and retain history
              </button>
              <button
                type="button"
                className="secondary"
                disabled={
                  !chosen.length ||
                  chosen.length >= issue.report_count ||
                  !lon ||
                  !lat
                }
                onClick={() => void save("split")}
              >
                Split selected reports
              </button>
            </div>
          </fieldset>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
      <h2>Issue history</h2>
      <ol>
        {issue.events.map((e, i) => (
          <li key={i}>
            {String(e.action).replaceAll("_", " ")} · {String(e.reason)} ·{" "}
            {new Date(String(e.created_at)).toLocaleString("en-IN")}
          </li>
        ))}
      </ol>
    </>
  );
}
