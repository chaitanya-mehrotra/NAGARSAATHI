import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import {
  api,
  type IssueSummary,
  type ReportDetail,
  type PriorityView,
  type Policy,
} from "../api/client";
import { SignIn, useSession } from "../session";

const names: Record<string, string> = {
  S: "Severity",
  A: "Age",
  R: "Independent reporters",
  L: "Location exposure",
  U: "Urgency",
};

export function PriorityExplanation({
  priority,
}: {
  priority: PriorityView | null | undefined;
}) {
  if (!priority)
    return (
      <p role="status">
        Priority calculation pending. This issue stays visible.
      </p>
    );
  return (
    <div className="priority-explanation">
      {!!priority.inputs.critical_review_due_at && (
        <p>
          Critical review due:{" "}
          {new Date(
            String(priority.inputs.critical_review_due_at),
          ).toLocaleString("en-IN")}
        </p>
      )}
      <p>
        <strong>
          {priority.score.toFixed(2)} / 100 · {priority.band}
        </strong>
        {priority.provisional ? " · provisional" : ""}
        {priority.stale ? " · stale — refresh pending" : ""}
      </p>
      <p>
        Policy {priority.policy_version} · POIs {priority.poi_version} ·
        computed {new Date(priority.computed_at).toLocaleString("en-IN")}
      </p>
      <dl>
        {Object.entries(priority.factors).map(([key, value]) => (
          <div key={key}>
            <dt>{names[key]}</dt>
            <dd>
              {value.toFixed(3)} factor →{" "}
              {priority.contributions[key].toFixed(2)} points
            </dd>
          </div>
        ))}
      </dl>
      <p>
        {priority.age_hours.toFixed(1)} hours old ·{" "}
        {Number(priority.inputs.eligible_reporters)} eligible authenticated
        reporters{priority.overdue ? " · past the pilot target" : ""}.
      </p>
      {priority.flags.length > 0 && (
        <ul>
          {priority.flags.map((f) => (
            <li key={f}>{f.replaceAll("_", " ")}</li>
          ))}
        </ul>
      )}
      <p className="hint">
        Priority is a proposed scheduling policy. Model confidence and area
        wealth do not affect the score.
      </p>
    </div>
  );
}

export function PriorityReview({
  issue,
  refresh,
}: {
  issue: IssueSummary;
  refresh: () => void;
}) {
  const { token } = useSession();
  const [severity, setSeverity] = useState(
    String(issue.priority?.inputs.severity_override ?? ""),
  );
  const [urgency, setUrgency] = useState(
    String(issue.priority?.inputs.urgency_override ?? ""),
  );
  const [critical, setCritical] = useState(issue.priority?.band === "critical");
  const [deadline, setDeadline] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [request, setRequest] = useState(crypto.randomUUID());
  async function save() {
    if (busy) return;
    if (reason.trim().length < 5 || (critical && !deadline)) {
      setError(
        "Supply a reason and a review deadline for a critical override.",
      );
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/priority/issues/${issue.id}/decision`, token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_version: issue.row_version,
          request_id: request,
          severity_override: severity === "" ? null : Number(severity),
          urgency_override: urgency === "" ? null : Number(urgency),
          critical_override: critical,
          critical_review_due_at: critical
            ? new Date(deadline).toISOString()
            : null,
          reason,
        }),
      });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Priority review failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h2>Priority explanation</h2>
      <PriorityExplanation priority={issue.priority} />
      {!issue.merged_into_id && issue.status !== "resolved" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
          onChange={() => setRequest(crypto.randomUUID())}
        >
          <fieldset disabled={busy}>
            <legend>Review severity and urgency</legend>
            <label htmlFor="priority-severity">Severity override</label>
            <select
              id="priority-severity"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            >
              <option value="">Use category baseline</option>
              <option value="0.25">Minor · 0.25</option>
              <option value="0.5">Standard · 0.50</option>
              <option value="0.75">Serious · 0.75</option>
              <option value="1">Critical severity · 1.00</option>
            </select>
            <label htmlFor="priority-urgency">Reviewed urgency</label>
            <select
              id="priority-urgency"
              value={urgency}
              onChange={(e) => setUrgency(e.target.value)}
            >
              <option value="">Pending review · provisional 0.50</option>
              <option value="0">Routine · 0</option>
              <option value="0.5">Time-sensitive · 0.50</option>
              <option value="1">Immediate concern · 1.00</option>
            </select>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={critical}
                onChange={(e) => setCritical(e.target.checked)}
              />{" "}
              Confirm critical scheduling override
            </label>
            <p className="hint">
              This override places the issue above numerical scores. An expired
              deadline flags re-review and keeps the hazard visible.
            </p>
            {critical && (
              <>
                <label htmlFor="critical-deadline">
                  Critical review deadline
                </label>
                <input
                  id="critical-deadline"
                  type="datetime-local"
                  value={deadline}
                  onChange={(e) => setDeadline(e.target.value)}
                />
              </>
            )}
            <label htmlFor="priority-reason">Priority decision reason</label>
            <textarea
              id="priority-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <button type="submit">Save priority review</button>
          </fieldset>
        </form>
      )}
      {error && (
        <p role="alert">
          {error} Reload the issue if another reviewer changed it.
        </p>
      )}
    </>
  );
}

export function PriorityQueue() {
  const { actor, token } = useSession();
  const [overdue, setOverdue] = useState(false);
  const issues = useQuery({
    queryKey: ["priority-ranking", actor?.id, overdue],
    enabled: !!actor,
    queryFn: () =>
      api<IssueSummary[]>(
        `/api/v1/priority/ranking${overdue ? "?overdue=true" : ""}`,
        token,
      ),
  });
  const hazards = useQuery({
    queryKey: ["rapid-review", actor?.id],
    enabled: !!actor,
    queryFn: () => api<ReportDetail[]>("/api/v1/priority/rapid-review", token),
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>Priority review</h1>
      <p>
        Confirmed critical overrides first, then score, original report age and
        stable issue identifier.
      </p>
      <h2>Rapid hazard review</h2>
      <p>
        Reported hazards can appear here before validation or duplicate review
        is complete.
      </p>
      {hazards.isError && <p role="alert">{hazards.error.message}</p>}
      {hazards.isPending && <p role="status">Loading hazard reports…</p>}
      <ul className="report-list">
        {hazards.data?.map((r) => (
          <li key={r.id}>
            <Link
              to={r.issue_id ? `/issues/${r.issue_id}` : `/reviews/${r.id}`}
            >
              <strong>{r.description}</strong>
              <span>
                Hazard reported · confirmation or re-review pending ·{" "}
                {r.state.replaceAll("_", " ")}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {hazards.data?.length === 0 && (
        <p>No pending reported hazards in your scope.</p>
      )}
      <h2>Ranked active issues</h2>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={overdue}
          onChange={(e) => setOverdue(e.target.checked)}
        />{" "}
        Only past the pilot target
      </label>
      <button
        className="secondary"
        onClick={() => {
          void issues.refetch();
          void hazards.refetch();
        }}
      >
        Refresh priority queue
      </button>
      {issues.isPending && <p role="status">Loading priorities…</p>}
      {issues.isError && <p role="alert">{issues.error.message}</p>}
      {issues.data?.length === 0 && <p>No matching active issues.</p>}
      <ol className="priority-list">
        {issues.data?.map((i) => (
          <li key={i.id}>
            <Link to={`/issues/${i.id}`}>
              {i.public_reference} · {i.category} · {i.area_code}
            </Link>
            <PriorityExplanation priority={i.priority} />
          </li>
        ))}
      </ol>
    </section>
  );
}

type EpochInfo = {
  id: string;
  pilot_id: string;
  poi_snapshot_id: string;
  version: string;
  state: string;
  poi_version: string;
};
type EpochDetail = {
  epoch: EpochInfo;
  policy: Policy;
  active_epoch_id: string;
  scores: {
    issue_id: string;
    public_reference: string;
    score: number;
    band: string;
    missing_data_flags: string[];
  }[];
};

export function PriorityPolicies() {
  const { actor, token } = useSession();
  const [selected, setSelected] = useState("");
  const epochs = useQuery({
    queryKey: ["priority-epochs", actor?.id],
    enabled: !!actor,
    queryFn: () => api<EpochInfo[]>("/api/v1/priority/policies", token),
  });
  const id = selected || epochs.data?.find((e) => e.state === "active")?.id;
  const detail = useQuery({
    queryKey: ["epoch-detail", id],
    enabled: !!id,
    queryFn: () => api<EpochDetail>(`/api/v1/priority/policies/${id}`, token),
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>Priority policies</h1>
      <p>
        Preview all active issues before switching the pilot to a new policy.
        Activation recomputes current evidence and switches the complete epoch
        atomically.
      </p>
      {epochs.isError && <p role="alert">{epochs.error.message}</p>}
      <label htmlFor="priority-epoch">Scoring epoch</label>
      <select
        id="priority-epoch"
        value={id || ""}
        onChange={(e) => setSelected(e.target.value)}
      >
        {epochs.data?.map((e) => (
          <option key={e.id} value={e.id}>
            {e.version} · {e.state} · {e.poi_version}
          </option>
        ))}
      </select>
      {detail.isPending && <p role="status">Loading policy…</p>}
      {detail.isError && <p role="alert">{detail.error.message}</p>}
      {detail.data && (
        <PolicyEditor
          key={id}
          detail={detail.data}
          created={(newId) => {
            setSelected(newId);
            void epochs.refetch();
          }}
          reload={() => {
            void epochs.refetch();
            void detail.refetch();
          }}
        />
      )}
    </section>
  );
}

function PolicyEditor({
  detail,
  created,
  reload,
}: {
  detail: EpochDetail;
  created: (id: string) => void;
  reload: () => void;
}) {
  const { token } = useSession();
  const [policy, setPolicy] = useState<Policy>(detail.policy);
  const [version, setVersion] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(activate: boolean) {
    setBusy(true);
    setError("");
    try {
      if (activate) {
        await api(
          `/api/v1/priority/policies/${detail.epoch.id}/activate`,
          token,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_active_epoch_id: detail.active_epoch_id,
              reason,
            }),
          },
        );
        reload();
      } else {
        const result = await api<{ id: string }>(
          "/api/v1/priority/policies/preview",
          token,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              pilot_id: detail.epoch.pilot_id,
              poi_snapshot_id: detail.epoch.poi_snapshot_id,
              policy: { ...policy, version },
              as_of: new Date().toISOString(),
              reason,
            }),
          },
        );
        created(result.id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Policy action failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h2>Preview scores</h2>
      <p>
        {detail.epoch.version} · {detail.epoch.state}. Context:{" "}
        {detail.epoch.poi_version}.
      </p>
      <ol>
        {detail.scores.slice(0, 50).map((s) => (
          <li key={s.issue_id}>
            <Link to={`/issues/${s.issue_id}`}>{s.public_reference}</Link> ·{" "}
            {s.score.toFixed(2)} · {s.band}
            {s.missing_data_flags.length ? " · provisional" : ""}
          </li>
        ))}
      </ol>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save(false);
        }}
      >
        <fieldset disabled={busy}>
          <legend>Proposed policy settings</legend>
          <label htmlFor="policy-version">New policy version</label>
          <input
            id="policy-version"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="demo-priority-v2"
          />
          <div className="form-grid">
            {Object.entries(policy.weights || {}).map(([key, value]) => (
              <div key={key}>
                <label htmlFor={`weight-${key}`}>{names[key]} weight</label>
                <input
                  id={`weight-${key}`}
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={value}
                  onChange={(e) =>
                    setPolicy({
                      ...policy,
                      weights: {
                        ...policy.weights,
                        [key]: Number(e.target.value),
                      },
                    })
                  }
                />
              </div>
            ))}
          </div>
          <p>
            Weights must sum to 1. Category targets are internal pilot settings.
          </p>
          {Object.entries(policy.categories).map(([key, value]) => (
            <div className="form-grid" key={key}>
              <div>
                <label htmlFor={`severity-${key}`}>
                  {key.replaceAll("_", " ")} baseline
                </label>
                <input
                  id={`severity-${key}`}
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={value.severity}
                  onChange={(e) =>
                    setPolicy({
                      ...policy,
                      categories: {
                        ...policy.categories,
                        [key]: { ...value, severity: Number(e.target.value) },
                      },
                    })
                  }
                />
              </div>
              <div>
                <label htmlFor={`target-${key}`}>
                  Target hours for {key.replaceAll("_", " ")}
                </label>
                <input
                  id={`target-${key}`}
                  type="number"
                  min="1"
                  value={value.target_hours}
                  onChange={(e) =>
                    setPolicy({
                      ...policy,
                      categories: {
                        ...policy.categories,
                        [key]: {
                          ...value,
                          target_hours: Number(e.target.value),
                        },
                      },
                    })
                  }
                />
              </div>
            </div>
          ))}
          <label htmlFor="policy-reason">Policy review reason</label>
          <textarea
            id="policy-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="actions">
            <button type="submit">Create policy preview</button>
            {detail.epoch.state === "preview" && (
              <button
                type="button"
                className="secondary"
                onClick={() => void save(true)}
              >
                Activate reviewed preview
              </button>
            )}
          </div>
        </fieldset>
      </form>
      {error && <p role="alert">{error}</p>}
    </>
  );
}
