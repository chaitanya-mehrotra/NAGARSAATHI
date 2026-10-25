import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api, type IssueSummary, type UploadReceipt } from "../api/client";
import { useSession, SignIn } from "../session";
import { PrivatePhoto } from "./citizen";

type WorkDetail = {
  issue: IssueSummary;
  archived_at: string | null;
  repairs: {
    id: string;
    notes: string;
    verification_state: string;
    evidence_media_ids: string[];
  }[];
  events: { action: string; reason: string; created_at: string }[];
};
export function WorkTasks() {
  const { actor, token } = useSession();
  const tasks = useQuery({
    queryKey: ["work-tasks", actor?.id],
    enabled: !!actor,
    queryFn: () => api<IssueSummary[]>("/api/v1/work", token),
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>My work tasks</h1>
      <button onClick={() => void tasks.refetch()}>Reload tasks</button>
      {tasks.isError && <p role="alert">{tasks.error.message}</p>}
      {tasks.data?.length === 0 && <p>No assigned tasks.</p>}
      {tasks.data?.map((i) => (
        <article key={i.id}>
          <h2>
            <Link to={`/work/${i.id}`}>{i.public_reference}</Link>
          </h2>
          <p>
            {i.category} · {i.area_code} · {i.status}
          </p>
        </article>
      ))}
    </section>
  );
}
export function WorkView() {
  const { id } = useParams();
  return (
    <section className="panel">
      <h1>Repair and verification</h1>
      <Link to="/work">My work tasks</Link>
      <WorkPanel id={id!} />
    </section>
  );
}
export function WorkPanel({ id }: { id: string }) {
  const { actor, token } = useSession();
  const [reason, setReason] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [media, setMedia] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const detail = useQuery({
    queryKey: ["work", actor?.id, id],
    enabled: !!actor,
    queryFn: () => api<WorkDetail>(`/api/v1/work/${id}`, token),
  });
  if (!actor) return <SignIn />;
  const record = detail.data;
  const reviewer = actor.grants.some((g) =>
    ["admin", "reviewer"].includes(g.role),
  );
  const assigned = record?.issue.assigned_operator_id === actor.id;
  async function act(action: string) {
    if (!record || busy) return;
    setBusy(true);
    setError("");
    try {
      let photo = media;
      if (action === "submit_repair" && !photo) {
        if (!file) throw new Error("Choose a repair photo");
        const uploaded = await api<UploadReceipt>("/api/v1/uploads", token, {
          method: "POST",
          headers: { "Content-Type": file.type },
          body: file,
        });
        await api(`/api/v1/uploads/${uploaded.id}/complete`, token, {
          method: "POST",
        });
        photo = uploaded.id;
        setMedia(photo);
      }
      await api(`/api/v1/work/${id}`, token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          expected_version: record.issue.row_version,
          action,
          reason,
          media_ids: action === "submit_repair" ? [photo] : [],
        }),
      });
      setMedia("");
      setFile(null);
      setReason("");
      await detail.refetch();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Work action failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="duplicate-card">
      <h2>Work lifecycle</h2>
      <button className="secondary" onClick={() => void detail.refetch()}>
        Reload work status
      </button>
      {detail.isPending && <p role="status">Loading work status…</p>}
      {detail.isError && <p role="alert">{detail.error.message}</p>}
      {record && (
        <>
          <p>
            {record.issue.status} · version {record.issue.row_version}
            {record.archived_at && " · Archived; evidence retained"}
          </p>
          <label>
            Work action reason
            <textarea
              minLength={5}
              maxLength={1000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          {assigned && record.issue.status === "in_progress" && (
            <label>
              Repair photo
              <input
                type="file"
                accept="image/png,image/jpeg"
                onChange={(e) => {
                  setFile(e.target.files?.[0] || null);
                  setMedia("");
                }}
              />
            </label>
          )}
          <div className="actions">
            {assigned &&
              ["assigned", "reopened"].includes(record.issue.status) && (
                <button
                  disabled={busy || reason.trim().length < 5}
                  onClick={() => void act("start")}
                >
                  Start work
                </button>
              )}
            {assigned && record.issue.status === "in_progress" && (
              <button
                disabled={busy || reason.trim().length < 5}
                onClick={() => void act("submit_repair")}
              >
                Submit repair for verification
              </button>
            )}
            {reviewer && record.issue.status === "resolution_pending" && (
              <>
                <button
                  disabled={busy || reason.trim().length < 5}
                  onClick={() => void act("verify")}
                >
                  Verify repair
                </button>
                <button
                  disabled={busy || reason.trim().length < 5}
                  onClick={() => void act("reject")}
                >
                  Reject repair
                </button>
              </>
            )}
            {reviewer && record.issue.status === "resolved" && (
              <>
                <button
                  disabled={
                    busy || reason.trim().length < 5 || !!record.archived_at
                  }
                  onClick={() => void act("archive")}
                >
                  Archive issue
                </button>
                <button
                  disabled={busy || reason.trim().length < 5}
                  onClick={() => void act("reopen")}
                >
                  Reopen issue
                </button>
              </>
            )}
          </div>
          {record.repairs.map((r) => (
            <article key={r.id}>
              <h3>Repair evidence · {r.verification_state}</h3>
              <p>{r.notes}</p>
              <div className="photo-grid">
                {r.evidence_media_ids.map((m) => (
                  <PrivatePhoto
                    key={m}
                    url={`/api/v1/media/${m}/content`}
                    alt="Repair evidence"
                  />
                ))}
              </div>
            </article>
          ))}
          <h3>Work history</h3>
          <ol>
            {record.events.map((e, n) => (
              <li key={n}>
                {e.action}: {e.reason} ·{" "}
                {new Date(e.created_at).toLocaleString("en-IN")}
              </li>
            ))}
          </ol>
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
