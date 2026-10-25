import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import {
  api,
  getJson,
  type PublicConfig,
  type ReportDetail,
} from "../api/client";
import { SignIn, useSession } from "../session";
import { PrivatePhoto } from "./citizen";

export function ReviewInbox() {
  const { actor, token } = useSession();
  const [filter, setFilter] = useState("all");
  const records = useQuery({
    queryKey: ["reviews", actor?.id],
    enabled: !!actor,
    queryFn: () => api<ReportDetail[]>("/api/v1/reviews", token),
    refetchInterval: 5000,
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>Review inbox</h1>
      <p>
        Only records in your database-granted scope are shown. Unassigned
        locations require a global reviewer or administrator.
      </p>
      <label htmlFor="review-filter">Review type</label>
      <select
        id="review-filter"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      >
        <option value="all">All pending reports</option>
        <option value="location">Location review</option>
        <option value="category">Category or photo review</option>
        <option value="error">Technical failure</option>
      </select>
      {records.isPending && <p role="status">Loading inbox…</p>}
      {records.isError && (
        <p role="alert">
          {records.error.message}{" "}
          <button onClick={() => void records.refetch()}>Retry inbox</button>
        </p>
      )}
      {records.data?.length === 0 && <p>No pending reports in your scope.</p>}
      <ul className="report-list">
        {records.data
          ?.filter(
            (item) =>
              filter === "all" ||
              (filter === "location" && !item.area_code) ||
              (filter === "error" && item.validation_status === "error") ||
              (filter === "category" && item.validation_status !== "accepted"),
          )
          .map((item) => (
            <li key={item.id}>
              <Link to={`/reviews/${item.id}`}>
                <strong>{item.description}</strong>
                {item.reported_hazard && (
                  <span>Immediate hazard reported · unconfirmed</span>
                )}
                <span>
                  {item.state.replaceAll("_", " ")} ·{" "}
                  {item.review_reason || "Awaiting processing"}
                </span>
                <small>{item.public_reference}</small>
              </Link>
            </li>
          ))}
      </ul>
    </section>
  );
}

export function ReviewDetail() {
  const { actor, token } = useSession();
  const { id } = useParams();
  const report = useQuery({
    queryKey: ["review", actor?.id, id],
    enabled: !!actor,
    queryFn: () => api<ReportDetail>(`/api/v1/reports/${id}`, token),
  });
  if (!actor) return <SignIn />;
  if (report.isError)
    return (
      <section className="panel">
        <h1>Review report</h1>
        <p role="alert">{report.error.message}</p>
      </section>
    );
  return (
    <section className="panel">
      <h1>Review report</h1>
      {report.data ? (
        <DecisionForm
          key={`${id}-${report.data.content_revision}`}
          report={report.data}
          token={token}
          refresh={() => void report.refetch()}
        />
      ) : (
        <p role="status">Loading evidence…</p>
      )}
      <Link to="/reviews">Back to review inbox</Link>
    </section>
  );
}

function DecisionForm({
  report,
  token,
  refresh,
}: {
  report: ReportDetail;
  token: string;
  refresh: () => void;
}) {
  const config = useQuery({
    queryKey: ["public-config"],
    queryFn: () => getJson<PublicConfig>("/api/v1/config/public"),
  });
  const [category, setCategory] = useState(
    report.canonical_category || report.claimed_category,
  );
  const point = report.canonical_location || report.location;
  const [lon, setLon] = useState(point.longitude?.toString() || "");
  const [lat, setLat] = useState(point.latitude?.toString() || "");
  const [reason, setReason] = useState("");
  const [asset, setAsset] = useState(report.trusted_asset_id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const request = useRef(crypto.randomUUID());
  async function save(decision: string) {
    if (reason.trim().length < 5) {
      setError("Record a reason of at least five characters.");
      return;
    }
    if (!!lon != !!lat) {
      setError("Supply both coordinates or leave both blank.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api<ReportDetail>(
        `/api/v1/reviews/${report.id}/decision`,
        token,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision: report.content_revision,
            request_id: request.current,
            decision,
            category: decision === "accepted" ? category : null,
            reason,
            trusted_asset_id: decision === "accepted" && asset ? asset : null,
            location:
              lon && lat
                ? {
                    longitude: Number(lon),
                    latitude: Number(lat),
                    confirmed: true,
                  }
                : null,
          }),
        },
      );
      setSuccess(`Decision recorded: ${result.validation_status}.`);
      refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Review failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <p className="tracking">{report.public_reference}</p>
      <p>{report.description}</p>
      <p>
        Claimed: {report.claimed_category} · Current validation:{" "}
        {report.validation_status}
      </p>
      <p>{report.review_reason || "No validation decision yet"}</p>
      <div className="photo-grid">
        {report.media.map((media, index) => (
          <PrivatePhoto
            key={media.id}
            url={media.content_url}
            alt={`Review evidence ${index + 1}`}
          />
        ))}
      </div>
      <form
        onSubmit={(e) => e.preventDefault()}
        onChange={() => {
          request.current = crypto.randomUUID();
          setSuccess("");
        }}
      >
        <fieldset disabled={busy}>
          <legend>Authoritative staff decision</legend>
          <label htmlFor="confirmed-category">Confirmed category</label>
          <select
            id="confirmed-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {config.data?.categories.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}
              </option>
            ))}
          </select>
          <p>
            Leave both coordinates blank for visual acceptance while location
            remains under review.
          </p>
          <div className="form-grid">
            <div>
              <label htmlFor="review-lon">Reviewed longitude</label>
              <input
                id="review-lon"
                type="number"
                step="any"
                value={lon}
                onChange={(e) => setLon(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="review-lat">Reviewed latitude</label>
              <input
                id="review-lat"
                type="number"
                step="any"
                value={lat}
                onChange={(e) => setLat(e.target.value)}
              />
            </div>
          </div>
          <label htmlFor="review-reason">Decision reason</label>
          <label htmlFor="trusted-asset">
            Verified inventory asset ID (optional)
          </label>
          <input
            id="trusted-asset"
            value={asset}
            onChange={(e) => setAsset(e.target.value)}
            placeholder="Verified inventory UUID"
          />
          <p>
            Only enter an inventory identifier you have verified against this
            physical asset.
          </p>
          <textarea
            id="review-reason"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="actions">
            <button
              type="button"
              disabled={config.isPending}
              onClick={() => void save("accepted")}
            >
              Accept evidence and category
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => void save("needs_review")}
            >
              Request clarification
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => void save("rejected")}
            >
              Reject evidence
            </button>
          </div>
        </fieldset>
      </form>
      {error && (
        <p role="alert">
          {error} Reload if another reviewer changed the record.
        </p>
      )}
      {success && <p role="status">{success}</p>}
    </>
  );
}
