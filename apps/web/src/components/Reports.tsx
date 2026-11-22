import { ReactNode, useEffect, useMemo, useState } from "react";
import { request } from "../services";
import { useI18n } from "../i18n";

// A category always keeps the same colour slot, so filtering never repaints the survivors.
const CATEGORY_ORDER = [
  "pothole",
  "waterlogging",
  "both",
  "electric_pole_fallen",
  "garbage_accumulation",
  "sewage_overflow",
  "streetlight_failure",
  "other_civic_issue",
];
const slot = (category: string) => {
  const i = CATEGORY_ORDER.indexOf(category);
  return `var(--series-${(i < 0 ? 7 : i) + 1})`;
};

type Summary = {
  as_of: string;
  range: { since: string; until: string; granularity: "day" | "week" };
  filters: { category: string | null; area: string | null };
  totals: { reports: number; flagged: number };
  by_status: Record<string, number>;
  by_category: { category: string; count: number }[];
  volume: { bucket: string; total: number; by_category: Record<string, number> }[];
  areas: { code: string; name: string; count: number; open: number }[];
  photo_check: { checked: number; unchecked: number; accepted: number; needs_review: number; flagged: number };
  resolution: {
    category: string;
    resolved: number;
    median_hours: number;
    p90_hours: number;
    target_hours: number;
    within_target: number;
  }[];
  backlog: { bucket: string; count: number }[];
  top_priorities: {
    id: string;
    reference: string;
    category: string;
    status: string;
    area: string;
    first_accepted_at: string;
    reports: number;
    score: number | null;
    band: string | null;
  }[];
};

const isoDay = (d: Date) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const daysAgo = (n: number) => isoDay(new Date(Date.now() - n * 86400000));

function niceMax(value: number) {
  if (value <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(value));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * pow >= value) return m * pow;
  return value;
}

function hoursText(h: number) {
  return h >= 48 ? `${(h / 24).toFixed(1)} d` : `${h.toFixed(1)} h`;
}

type Bar = { key: string; label: string; value: number; color: string; note?: string };

/** Horizontal bars as plain HTML so labels keep a readable size in narrow panels. */
function HBars({ rows, unit = "" }: { rows: Bar[]; unit?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="hbars">
      {rows.map((r) => (
        <li key={r.key} title={`${r.label}: ${r.value}${unit}${r.note ? " · " + r.note : ""}`}>
          <span className="hb-label">{r.label}</span>
          <span className="hb-track">
            <i style={{ width: `${Math.max(1, (r.value / max) * 100)}%`, background: r.color }} />
          </span>
          <span className="hb-value">
            {r.value}
            {unit}
          </span>
        </li>
      ))}
    </ul>
  );
}

function VolumeChart({ data, locale, t }: { data: Summary["volume"]; locale?: string; t: (k: string, v?: any) => string }) {
  const W = 640;
  const H = 230;
  const left = 36;
  const bottom = 26;
  const top = 8;
  const plotW = W - left - 8;
  const plotH = H - bottom - top;
  const max = niceMax(Math.max(1, ...data.map((d) => d.total)));
  const step = plotW / Math.max(1, data.length);
  const barW = Math.max(3, Math.min(26, step * 0.7));
  const every = Math.ceil(data.length / 6);
  const fmt = (iso: string) =>
    new Date(iso + "T00:00:00").toLocaleDateString(locale, { day: "numeric", month: "short" });
  const ticks = [0, 0.5, 1].map((f) => Math.round(max * f));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img">
      {ticks.map((v) => {
        const y = top + plotH - (v / max) * plotH;
        return (
          <g key={v}>
            <line x1={left} x2={W - 8} y1={y} y2={y} className="chart-grid" />
            <text x={left - 6} y={y + 4} textAnchor="end" className="chart-axis">
              {v}
            </text>
          </g>
        );
      })}
      {data.map((d, i) => {
        const x = left + i * step + (step - barW) / 2;
        let y = top + plotH;
        const parts = CATEGORY_ORDER.concat(Object.keys(d.by_category).filter((c) => !CATEGORY_ORDER.includes(c)))
          .filter((c) => d.by_category[c])
          .map((c) => {
            const h = (d.by_category[c] / max) * plotH;
            y -= h;
            return <rect key={c} x={x} y={y} width={barW} height={Math.max(0, h)} fill={slot(c)} className="chart-seg" />;
          });
        return (
          <g key={d.bucket}>
            <title>{`${fmt(d.bucket)}: ${d.total}`}</title>
            {parts}
            {i % every === 0 && (
              <text x={x + barW / 2} y={H - 8} textAnchor="middle" className="chart-axis">
                {fmt(d.bucket)}
              </text>
            )}
          </g>
        );
      })}
      <text x={W - 8} y={H - 8} textAnchor="end" className="chart-axis">
        {data.length > 0 ? t("reports.granularity." + (data.length > 31 || data.length < 2 ? "week" : "day")) : ""}
      </text>
    </svg>
  );
}

function Panel({ title, note, children, wide }: { title: string; note?: string; children: ReactNode; wide?: boolean }) {
  return (
    <section className={"card report-panel" + (wide ? " wide" : "")}>
      <h2>{title}</h2>
      {note && <p className="report-note">{note}</p>}
      {children}
    </section>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="audit-table-wrap">
      <table className="audit-table">
        <thead>
          <tr>{head.map((h) => <th key={h}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function csvCell(v: unknown) {
  const s = String(v ?? "");
  const safe = /^[=+\-@\t\r]/.test(s) ? "'" + s : s;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function Reports() {
  const { t, locale } = useI18n();
  const [filters, setFilters] = useState({ since: daysAgo(29), until: daysAgo(0), category: "", area: "" });
  const [applied, setApplied] = useState(filters);
  const [data, setData] = useState<Summary | null>(null);
  const [areaOptions, setAreaOptions] = useState<{ code: string; name: string }[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [asTable, setAsTable] = useState(false);

  const label = (key: string) => {
    const text = t(`issue.${key}`);
    return text === `issue.${key}` ? key.replace(/_/g, " ") : text;
  };
  const statusText = (key: string) => {
    const text = t(`status.${key}`);
    return text === `status.${key}` ? key : text;
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(applied)) if (v) params.set(k, v);
    request(`/api/v1/analytics/summary?${params}`)
      .then((d: Summary) => {
        if (!active) return;
        setData(d);
        if (!applied.area) setAreaOptions(d.areas.filter((a) => a.code !== "unassigned"));
      })
      .catch((e) => active && setError(e?.message || t("reports.error")))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [applied]);

  const categoryRows = useMemo<Bar[]>(
    () => (data?.by_category ?? []).map((c) => ({ key: c.category, label: label(c.category), value: c.count, color: slot(c.category) })),
    [data, t],
  );

  const exportCsv = () => {
    if (!data) return;
    const rows: unknown[][] = [
      ["section", "name", "value", "extra"],
      ["range", data.range.since, data.range.until, data.range.granularity],
      ...data.volume.flatMap((v) =>
        Object.entries(v.by_category).map(([c, n]) => ["volume", v.bucket, n, c]),
      ),
      ...Object.entries(data.by_status).map(([s, n]) => ["status", s, n, ""]),
      ...data.by_category.map((c) => ["category", c.category, c.count, ""]),
      ...data.areas.map((a) => ["area", a.name, a.count, `open ${a.open}`]),
      ...data.backlog.map((b) => ["backlog_days", b.bucket, b.count, ""]),
      ...data.resolution.map((r) => ["resolution_hours", r.category, r.median_hours, `p90 ${r.p90_hours}; resolved ${r.resolved}; within target ${r.within_target}`]),
      ...data.top_priorities.map((p) => ["top_priority", p.reference, p.score ?? "", `${p.category}; ${p.area}; ${p.status}`]),
    ];
    const csv = rows.map((r) => r.map(csvCell).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `nagarsaathi-report-${data.range.since}_${data.range.until}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const open = data ? (data.by_status.open ?? 0) + (data.by_status.in_progress ?? 0) : 0;
  const median = data && data.resolution.length
    ? [...data.resolution].sort((a, b) => b.resolved - a.resolved)[0]
    : null;
  const backlogColors = ["#86b6ef", "#3987e5", "#256abf", "#104281"];
  const photo = data?.photo_check;

  return (
    <div className="reports-page">
      <div className="page-heading">
        <h1>{t("page.Reports.h")}</h1>
        <p>{t("page.Reports.p")}</p>
      </div>

      <form
        className="card audit-filters no-print"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(filters);
        }}
      >
        <label>
          <span className="field-label">{t("audit.filter.from")}</span>
          <input type="date" value={filters.since} max={filters.until} onChange={(e) => setFilters({ ...filters, since: e.target.value })} />
        </label>
        <label>
          <span className="field-label">{t("audit.filter.to")}</span>
          <input type="date" value={filters.until} min={filters.since} onChange={(e) => setFilters({ ...filters, until: e.target.value })} />
        </label>
        <label>
          <span className="field-label">{t("reports.filter.category")}</span>
          <select value={filters.category} onChange={(e) => setFilters({ ...filters, category: e.target.value })}>
            <option value="">{t("reports.filter.all")}</option>
            {CATEGORY_ORDER.map((c) => (
              <option key={c} value={c}>{label(c)}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="field-label">{t("reports.filter.area")}</span>
          <select value={filters.area} onChange={(e) => setFilters({ ...filters, area: e.target.value })}>
            <option value="">{t("reports.filter.all")}</option>
            {areaOptions.map((a) => (
              <option key={a.code} value={a.code}>{a.name}</option>
            ))}
          </select>
        </label>
        <button className="primary" type="submit">{t("audit.apply")}</button>
        <button type="button" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          {asTable ? t("reports.showCharts") : t("reports.showTables")}
        </button>
        <button type="button" onClick={exportCsv} disabled={!data}>{t("audit.export")}</button>
        <button type="button" onClick={() => window.print()}>{t("reports.print")}</button>
      </form>

      {error && <p role="alert">{error}</p>}
      {loading && !data && <p>{t("reports.loading")}</p>}

      {data && (
        <div className={loading ? "reports-body busy" : "reports-body"}>
          <p className="report-note">
            {t("reports.scope", {
              since: new Date(data.range.since + "T00:00:00").toLocaleDateString(locale),
              until: new Date(data.range.until + "T00:00:00").toLocaleDateString(locale),
              time: new Date(data.as_of).toLocaleString(locale),
            })}
          </p>

          <div className="stat-row">
            <div className="stat-tile"><span>{t("reports.stat.total")}</span><strong>{data.totals.reports}</strong></div>
            <div className="stat-tile"><span>{t("reports.stat.open")}</span><strong>{open}</strong></div>
            <div className="stat-tile"><span>{t("status.resolved")}</span><strong>{data.by_status.resolved ?? 0}</strong></div>
            <div className="stat-tile">
              <span>{t("reports.stat.flagged")}</span>
              <strong>{data.totals.flagged}</strong>
              <small>{data.totals.reports ? Math.round((data.totals.flagged / data.totals.reports) * 100) : 0}%</small>
            </div>
            <div className="stat-tile">
              <span>{t("reports.stat.median")}</span>
              <strong>{median ? hoursText(median.median_hours) : "—"}</strong>
              {median && <small>{label(median.category)}</small>}
            </div>
          </div>

          {data.totals.reports === 0 && <p className="audit-empty">{t("reports.empty")}</p>}

          <div className="report-grid">
            <Panel title={t("reports.volume")} note={t("reports.volumeNote")} wide>
              {asTable ? (
                <Table
                  head={[t("audit.col.when"), t("reports.total"), ...CATEGORY_ORDER.map(label)]}
                  rows={data.volume.map((v) => [v.bucket, v.total, ...CATEGORY_ORDER.map((c) => v.by_category[c] ?? 0)])}
                />
              ) : (
                <>
                  <VolumeChart data={data.volume} locale={locale} t={t} />
                  <ul className="legend">
                    {CATEGORY_ORDER.filter((c) => data.by_category.some((b) => b.category === c)).map((c) => (
                      <li key={c}><i style={{ background: slot(c) }} />{label(c)}</li>
                    ))}
                  </ul>
                </>
              )}
            </Panel>

            <Panel title={t("reports.byStatus")} note={t("reports.byStatusNote")}>
              {asTable ? (
                <Table head={[t("audit.col.action"), t("reports.total")]} rows={Object.entries(data.by_status).map(([s, n]) => [statusText(s), n])} />
              ) : (
                <HBars
                  rows={Object.entries(data.by_status).map(([s, n], i) => ({
                    key: s,
                    label: statusText(s),
                    value: n,
                    color: ["#86b6ef", "#5598e7", "#256abf", "#184f95", "#6b787b", "#b3392b"][i] ?? "#256abf",
                  }))}
                />
              )}
            </Panel>

            <Panel title={t("reports.byCategory")}>
              {asTable ? (
                <Table head={[t("reports.filter.category"), t("reports.total")]} rows={categoryRows.map((r) => [r.label, r.value])} />
              ) : (
                <HBars rows={categoryRows} />
              )}
            </Panel>

            <Panel title={t("reports.resolution")} note={t("reports.resolutionNote")}>
              {data.resolution.length === 0 ? (
                <p className="audit-empty">{t("reports.noneResolved")}</p>
              ) : asTable ? (
                <Table
                  head={[t("reports.filter.category"), t("status.resolved"), t("reports.median"), "P90", t("reports.target"), t("reports.withinTarget")]}
                  rows={data.resolution.map((r) => [label(r.category), r.resolved, hoursText(r.median_hours), hoursText(r.p90_hours), hoursText(r.target_hours), `${r.within_target}/${r.resolved}`])}
                />
              ) : (
                <>
                  <HBars
                    unit=" h"
                    rows={data.resolution.map((r) => ({
                      key: r.category,
                      label: label(r.category),
                      value: r.median_hours,
                      color: slot(r.category),
                      note: `P90 ${hoursText(r.p90_hours)} · ${r.within_target}/${r.resolved} ${t("reports.withinTarget")}`,
                    }))}
                  />
                  <p className="report-note">{t("reports.medianHint")}</p>
                </>
              )}
            </Panel>

            <Panel title={t("reports.backlog")} note={t("reports.backlogNote")}>
              {asTable ? (
                <Table head={[t("reports.age"), t("reports.total")]} rows={data.backlog.map((b) => [b.bucket, b.count])} />
              ) : (
                <HBars rows={data.backlog.map((b, i) => ({ key: b.bucket, label: `${b.bucket} ${t("reports.days")}`, value: b.count, color: backlogColors[i] }))} />
              )}
            </Panel>

            <Panel title={t("reports.hotspots")} note={t("reports.hotspotsNote")}>
              {asTable ? (
                <Table head={[t("reports.filter.area"), t("reports.total"), t("reports.stat.open")]} rows={data.areas.map((a) => [a.name, a.count, a.open])} />
              ) : (
                <HBars rows={data.areas.map((a) => ({ key: a.code, label: a.name, value: a.count, color: "#256abf", note: `${a.open} ${t("reports.stat.open")}` }))} />
              )}
            </Panel>

            <Panel title={t("reports.photo")} note={t("reports.photoNote")}>
              {photo && (
                <Table
                  head={[t("audit.col.action"), t("reports.total")]}
                  rows={[
                    [t("reports.photo.checked"), photo.checked],
                    [t("reports.photo.accepted"), photo.accepted],
                    [t("reports.photo.review"), photo.needs_review],
                    [t("reports.photo.waiting"), photo.unchecked],
                    [t("reports.photo.flagged"), photo.flagged],
                  ]}
                />
              )}
            </Panel>

            <Panel title={t("reports.top")} note={t("reports.topNote")} wide>
              {data.top_priorities.length === 0 ? (
                <p className="audit-empty">{t("reports.noneOpen")}</p>
              ) : (
                <Table
                  head={[t("audit.col.report"), t("reports.filter.category"), t("reports.filter.area"), t("audit.col.action"), t("reports.score"), t("reports.reportsCount")]}
                  rows={data.top_priorities.map((p) => [p.reference, label(p.category), p.area, statusText(p.status), p.score ?? "—", p.reports])}
                />
              )}
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
