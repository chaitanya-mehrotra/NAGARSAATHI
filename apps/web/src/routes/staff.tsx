import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams, useNavigate } from "react-router";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  api,
  getJson,
  type PublicConfig,
  type IssueSummary,
} from "../api/client";
import type { components } from "@nagarsaathi/contracts";
import { SignIn, useSession } from "../session";

type QueuePage = components["schemas"]["QueuePage"];
type AreaSummary = components["schemas"]["AreaCategorySummary"];
type Assignee = components["schemas"]["Assignee"];
maplibregl.setWorkerUrl(workerUrl);

function QueueMap({
  items,
  onBounds,
  returnTo,
}: {
  items: QueuePage["items"];
  onBounds: (value: string) => void;
  returnTo: string;
}) {
  const navigate = useNavigate();
  const root = useRef<HTMLDivElement>(null);
  const instance = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const fitted = useRef(false);
  const callback = useRef(onBounds);
  callback.current = onBounds;
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setFailed(false);
    fitted.current = false;
    try {
      const map = new maplibregl.Map({
        container: root.current!,
        center: [77.645, 12.93],
        zoom: 12,
        style: {
          version: 8,
          sources: {},
          layers: [
            {
              id: "background",
              type: "background",
              paint: { "background-color": "#e5ede5" },
            },
          ],
        },
        attributionControl: false,
      });
      instance.current = map;
      const bounds = () => {
        const b = map.getBounds();
        callback.current(
          [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
            .map((v) => v.toFixed(6))
            .join(","),
        );
      };
      map.on("moveend", bounds);
      map.on("error", () => active && setFailed(true));
      map.on("load", () => {
        bounds();
        fetch("/api/v1/config/boundaries")
          .then((r) => {
            if (!r.ok) throw new Error("Map unavailable");
            return r.json();
          })
          .then((data) => {
            if (!active) return;
            map.addSource("areas", { type: "geojson", data });
            map.addLayer({
              id: "areas",
              type: "line",
              source: "areas",
              paint: { "line-color": "#466d60", "line-width": 2 },
            });
          })
          .catch(() => active && setFailed(true));
      });
    } catch {
      setFailed(true);
    }
    return () => {
      active = false;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      instance.current?.remove();
      instance.current = null;
    };
  }, [retry]);
  useEffect(() => {
    const map = instance.current;
    if (!map) return;
    markers.current.forEach((m) => m.remove());
    markers.current = items.map(({ issue, position }) => {
      const anchor = document.createElement("a");
      anchor.className = "queue-marker";
      anchor.dataset.issueId = issue.id;
      anchor.textContent = String(position);
      anchor.href = `/issues/${issue.id}?returnTo=${encodeURIComponent(returnTo)}`;
      anchor.onclick = (event) => {
        if (
          !event.ctrlKey &&
          !event.metaKey &&
          !event.shiftKey &&
          !event.altKey
        ) {
          event.preventDefault();
          navigate(
            `/issues/${issue.id}?returnTo=${encodeURIComponent(returnTo)}`,
          );
        }
      };
      anchor.setAttribute(
        "aria-label",
        `${position}. ${issue.public_reference}, ${issue.category}`,
      );
      return new maplibregl.Marker({ element: anchor })
        .setLngLat([issue.point.longitude!, issue.point.latitude!])
        .addTo(map);
    });
    if (items.length && !fitted.current) {
      fitted.current = true;
      const b = new maplibregl.LngLatBounds();
      items.forEach(({ issue }) =>
        b.extend([issue.point.longitude!, issue.point.latitude!]),
      );
      map.fitBounds(b, { padding: 45, maxZoom: 16, duration: 0 });
    }
  }, [items, returnTo, retry, navigate]);
  return (
    <>
      <div ref={root} className="pin-map" aria-label="Ranked issue map" />
      {failed ? (
        <div role="alert">
          Map unavailable. The ranked list remains usable.{" "}
          <button className="secondary" onClick={() => setRetry((v) => v + 1)}>
            Retry map
          </button>
        </div>
      ) : (
        <p className="hint">
          Demo area outlines; no street tiles. Numbered pins show this page in
          list order.
        </p>
      )}
    </>
  );
}

export function StaffQueue() {
  const { actor, token } = useSession();
  const [search, setSearch] = useSearchParams();
  const [bounds, setBounds] = useState("");
  const [refresh, setRefresh] = useState(0);
  const config = useQuery({
    queryKey: ["public-config"],
    queryFn: () => getJson<PublicConfig>("/api/v1/config/public"),
  });
  const areas = useQuery({
    queryKey: ["staff-areas", actor?.id],
    enabled: !!actor,
    queryFn: () => api<AreaSummary[]>("/api/v1/areas/summary", token),
  });
  const query = search.toString();
  const returnTo = `/staff${query ? `?${query}` : ""}`;
  const records = useQuery({
    queryKey: ["staff-queue", actor?.id, query, refresh],
    enabled: !!actor,
    queryFn: () => api<QueuePage>(`/api/v1/staff/queue?${query}`, token),
    staleTime: 0,
  });
  function filter(key: string, value: string) {
    const next = new URLSearchParams(search);
    next.delete("cursor");
    value ? next.set(key, value) : next.delete(key);
    setSearch(next);
  }
  if (!actor) return <SignIn />;
  const areaOptions = [
    ...new Map(areas.data?.map((a) => [a.area_code, a.area_name])).entries(),
  ];
  return (
    <section className="panel staff-panel">
      <h1>Staff work queue</h1>
      <p>
        Confirmed critical issues first, then score, oldest evidence and stable
        issue ID.
      </p>
      <Link to="/staff/areas">Compare service areas</Link>
      <div className="queue-filters">
        <label>
          Service area
          <select
            value={search.get("area") || ""}
            onChange={(e) => filter("area", e.target.value)}
          >
            <option value="">All permitted areas</option>
            {areaOptions.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Category
          <select
            value={search.get("category") || ""}
            onChange={(e) => filter("category", e.target.value)}
          >
            <option value="">All categories</option>
            {config.data?.categories.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={search.get("status") || "active"}
            onChange={(e) => filter("status", e.target.value)}
          >
            {[
              "active",
              "open",
              "assigned",
              "in_progress",
              "resolution_pending",
              "reopened",
              "resolved",
              "merged",
              "all",
            ].map((v) => (
              <option key={v} value={v}>
                {v.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <label>
          Priority band
          <select
            value={search.get("band") || ""}
            onChange={(e) => filter("band", e.target.value)}
          >
            <option value="">All bands</option>
            {["critical", "high", "medium", "low", "pending"].map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={search.get("overdue") === "true"}
            onChange={(e) => filter("overdue", e.target.checked ? "true" : "")}
          />{" "}
          Overdue only
        </label>
      </div>
      <div className="actions">
        <button
          onClick={() => {
            const next = new URLSearchParams(search);
            next.delete("cursor");
            setSearch(next);
            setRefresh((v) => v + 1);
          }}
        >
          Refresh ranking
        </button>
        <button className="secondary" onClick={() => setSearch({})}>
          Clear filters
        </button>
      </div>
      {areas.isError && <p role="alert">{areas.error.message}</p>}
      {records.isPending && <p role="status">Loading work queue…</p>}
      {records.isError && <p role="alert">{records.error.message}</p>}
      {records.data && (
        <>
          <p className="tracking">
            {records.data.total_issues} issues ·{" "}
            {records.data.total_linked_reports} linked reports
          </p>
          <p className="hint">
            Captured{" "}
            {new Date(records.data.captured_at).toLocaleString("en-IN")}.
            Browsing expires after 15 minutes. Reporter–issue pairs:{" "}
            {records.data.eligible_reporter_issue_pairs}; one person may support
            several issues. These counts are not unique residents.
          </p>
          <QueueMap
            items={records.data.items}
            onBounds={setBounds}
            returnTo={returnTo}
          />
          <div className="actions">
            <button
              className="secondary"
              disabled={!bounds}
              onClick={() => filter("bbox", bounds)}
            >
              Filter this map view
            </button>
            {search.has("bbox") && (
              <button className="secondary" onClick={() => filter("bbox", "")}>
                Remove map bounds filter
              </button>
            )}
          </div>
          {search.has("bbox") && (
            <p className="hint">Bounds: {search.get("bbox")}</p>
          )}
          {records.data.items.length === 0 && (
            <p>No issues match these filters.</p>
          )}
          <ol className="queue-list">
            {records.data.items.map(
              ({ issue, position, changed_since_capture }) => (
                <li
                  className="queue-entry"
                  key={issue.id}
                  data-issue-id={issue.id}
                  value={position}
                >
                  <h2>
                    <Link
                      to={`/issues/${issue.id}?returnTo=${encodeURIComponent(returnTo)}`}
                    >
                      {issue.public_reference}
                    </Link>
                  </h2>
                  <p>
                    {issue.category} · {issue.area_code} · {issue.status}
                  </p>
                  <p>
                    {issue.priority
                      ? `${issue.priority.band} · score ${issue.priority.score.toFixed(1)}`
                      : "Priority pending"}
                    {issue.priority?.stale && " · Stale score"}
                    {issue.priority?.provisional && " · Provisional inputs"}
                  </p>
                  <p>
                    {issue.report_count} linked reports ·{" "}
                    {issue.eligible_reporter_count} eligible reporters for this
                    issue
                  </p>
                  {issue.assigned_team && <p>Team: {issue.assigned_team}</p>}
                  {changed_since_capture && (
                    <p className="notice">
                      Updated since capture. Refresh ranking to include the
                      changes.
                    </p>
                  )}
                </li>
              ),
            )}
          </ol>
          <div className="actions">
            {search.has("cursor") && (
              <button
                className="secondary"
                onClick={() => filter("cursor", "")}
              >
                First page
              </button>
            )}
            {records.data.next_cursor && (
              <button
                onClick={() => {
                  const next = new URLSearchParams(search);
                  next.set("cursor", records.data!.next_cursor!);
                  setSearch(next);
                }}
              >
                Next page
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}

export function AreaOverview() {
  const { actor, token } = useSession();
  const records = useQuery({
    queryKey: ["staff-areas", actor?.id],
    enabled: !!actor,
    queryFn: () => api<AreaSummary[]>("/api/v1/areas/summary", token),
  });
  if (!actor) return <SignIn />;
  const grouped = new Map<string, AreaSummary[]>();
  records.data?.forEach((r) =>
    grouped.set(r.area_code, [...(grouped.get(r.area_code) || []), r]),
  );
  return (
    <section className="panel staff-panel">
      <h1>Service area overview</h1>
      <Link to="/staff">Staff work queue</Link>
      <p>
        Current active issues by category. Linked reports measure evidence
        volume; several reports can describe one issue.
      </p>
      <button className="secondary" onClick={() => void records.refetch()}>
        Refresh area counts
      </button>
      {records.isPending && <p role="status">Loading service areas…</p>}
      {records.isError && <p role="alert">{records.error.message}</p>}
      {[...grouped].map(([code, rows]) => (
        <article key={code} className="duplicate-card">
          <h2>{rows[0].area_name}</h2>
          <Link to={`/staff?area=${code}`}>Open this area’s queue</Link>
          <div className="area-category-grid">
            {rows.map((r) => (
              <section key={r.category}>
                <h3>
                  <Link to={`/staff?area=${code}&category=${r.category}`}>
                    {r.category.replaceAll("_", " ")}
                  </Link>
                </h3>
                <p>
                  {r.active_issues} issues · {r.linked_reports} reports
                </p>
                <p>
                  {r.high_or_critical_issues} high or critical ·{" "}
                  {r.overdue_issues} overdue
                </p>
                <p>
                  {r.confirmed_critical_issues} confirmed critical ·{" "}
                  {r.high_and_overdue_issues} high and overdue
                </p>
                <p className="hint">
                  Oldest:{" "}
                  {r.oldest_age_hours === null
                    ? "No active issues"
                    : `${r.oldest_age_hours.toFixed(1)} hours`}
                </p>
              </section>
            ))}
          </div>
        </article>
      ))}
    </section>
  );
}

export function AssignmentPanel({
  issue,
  refresh,
}: {
  issue: IssueSummary;
  refresh: () => void;
}) {
  const { token } = useSession();
  const options = useQuery({
    queryKey: ["assignees", issue.id],
    queryFn: () =>
      api<Assignee[]>(`/api/v1/issues/${issue.id}/assignees`, token),
  });
  const [operator, setOperator] = useState(issue.assigned_operator_id || "");
  const [team, setTeam] = useState(issue.assigned_team || "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(crypto.randomUUID());
  if (!["open", "assigned", "reopened"].includes(issue.status)) return null;
  return (
    <section className="duplicate-card">
      <h2>Assignment</h2>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          setBusy(true);
          setError("");
          try {
            await api(`/api/v1/issues/${issue.id}/assign`, token, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                request_id: request.current,
                expected_version: issue.row_version,
                operator_id: operator || null,
                team: operator && team.trim() ? team.trim() : null,
                reason,
              }),
            });
            refresh();
          } catch (e) {
            setError(e instanceof Error ? e.message : "Assignment failed");
          } finally {
            setBusy(false);
          }
        }}
        onChange={() => {
          request.current = crypto.randomUUID();
        }}
      >
        <label>
          Assigned operator
          <select
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
          >
            <option value="">Unassigned</option>
            {options.data?.map((o) => (
              <option key={o.id} value={o.id}>
                {o.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Team label (optional)
          <input
            maxLength={100}
            value={team}
            disabled={!operator}
            onChange={(e) => setTeam(e.target.value)}
          />
        </label>
        <p className="hint">
          Only active operators permitted in this area can be assigned. A team
          label grants no access.
        </p>
        <label>
          Assignment reason
          <textarea
            required
            minLength={5}
            maxLength={1000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        {(error || options.isError) && (
          <p role="alert">{error || options.error?.message}</p>
        )}
        <button disabled={busy || !options.data}>
          {busy ? "Saving…" : "Save assignment"}
        </button>
      </form>
    </section>
  );
}
