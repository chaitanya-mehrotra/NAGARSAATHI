import { useCallback, useEffect, useState } from "react";
import { request } from "../services";
import { useI18n } from "../i18n";
import { AuditEvent, useActionName } from "./History";

const KNOWN_ACTIONS = [
  "report_submitted", "photo_checked", "photo_reviewed", "review_report", "status_override",
  "status_changed", "report_linked", "report_unlinked", "soft_delete", "restore",
  "deduplication_delete", "assigned", "start", "submit_repair", "verify", "reject", "reopen", "archive",
  "merged", "split", "report_reclassified", "priority_reviewed",
];

const emptyFilters = { action: "", report_id: "", since: "", until: "" };

function query(filters: typeof emptyFilters, extra: Record<string, string> = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...filters, ...extra })) {
    if (value.trim()) params.set(key, value.trim());
  }
  return params.toString();
}

/** Short, readable summary of what an event carried (model result, link method, notes). */
function summary(e: AuditEvent): string {
  const parts: string[] = [];
  if (e.reason) parts.push(e.reason);
  const d = e.details ?? {};
  if (e.action === "photo_checked" || e.action === "photo_reviewed") {
    const labels = Array.isArray(d.labels) ? d.labels : [];
    const text = labels
      .map((l: any) => `${l.label} ${(Number(l.confidence) * 100).toFixed(0)}%`)
      .join(", ");
    parts.push([e.to_state, text].filter(Boolean).join(": "));
  } else if (e.to_state) {
    parts.push((e.from_state ? e.from_state + " → " : "→ ") + e.to_state);
  }
  return parts.filter(Boolean).join(" · ");
}

export function AuditLog({ onOpenReport }: { onOpenReport?: (reportId: string) => void }) {
  const { t, locale } = useI18n();
  const actionName = useActionName();
  const [draft, setDraft] = useState(emptyFilters);
  const [applied, setApplied] = useState(emptyFilters);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(
    async (filters: typeof emptyFilters, before?: string) => {
      setLoading(true);
      setError(false);
      try {
        const data = await request(
          `/api/v1/audit?${query(filters, { limit: "50", ...(before ? { before } : {}) })}`,
        );
        setEvents((old) => (before ? [...old, ...data.events] : data.events));
        setNext(data.next_before);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(applied);
  }, [applied, load]);

  const download = async () => {
    try {
      const csv = await request(`/api/v1/audit/export.csv?${query(applied)}`);
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "audit-log.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setError(true);
    }
  };

  return (
    <>
      <div className="page-heading">
        <h1>{t("page.Audit Log.h")}</h1>
        <p>{t("page.Audit Log.p")}</p>
      </div>
      <form
        className="card audit-filters"
        onSubmit={(ev) => {
          ev.preventDefault();
          setApplied(draft);
        }}
      >
        <label>
          <span className="field-label">{t("audit.filter.action")}</span>
          <select value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })}>
            <option value="">{t("audit.filter.allActions")}</option>
            {KNOWN_ACTIONS.map((a) => (
              <option key={a} value={a}>
                {actionName(a)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="field-label">{t("audit.filter.report")}</span>
          <input
            value={draft.report_id}
            onChange={(e) => setDraft({ ...draft, report_id: e.target.value })}
            placeholder="xxxxxxxx-xxxx-…"
          />
        </label>
        <label>
          <span className="field-label">{t("audit.filter.from")}</span>
          <input type="date" value={draft.since} onChange={(e) => setDraft({ ...draft, since: e.target.value })} />
        </label>
        <label>
          <span className="field-label">{t("audit.filter.to")}</span>
          <input type="date" value={draft.until} onChange={(e) => setDraft({ ...draft, until: e.target.value })} />
        </label>
        <button className="primary" type="submit">
          {t("audit.apply")}
        </button>
        <button type="button" onClick={download}>
          {t("audit.export")}
        </button>
      </form>

      {error && <p role="alert">{t("audit.error")}</p>}
      <div className="card audit-table-wrap">
        <table className="audit-table">
          <thead>
            <tr>
              <th>{t("audit.col.when")}</th>
              <th>{t("audit.col.who")}</th>
              <th>{t("audit.col.action")}</th>
              <th>{t("audit.col.report")}</th>
              <th>{t("audit.col.details")}</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => (
              <tr key={i}>
                <td>{new Date(e.occurred_at).toLocaleString(locale)}</td>
                <td>{e.actor_name ?? t("audit.system")}</td>
                <td>{actionName(e.action)}</td>
                <td>
                  {e.report_id && onOpenReport ? (
                    <button type="button" className="link-button" onClick={() => onOpenReport(e.report_id!)}>
                      {e.report_id.slice(0, 8)}
                    </button>
                  ) : (
                    e.report_id?.slice(0, 8) ?? "—"
                  )}
                </td>
                <td>{summary(e)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !error && events.length === 0 && <p className="audit-empty">{t("audit.empty")}</p>}
        {loading && <p className="audit-empty">{t("audit.loading")}</p>}
        {next && !loading && (
          <button type="button" onClick={() => load(applied, next)}>
            {t("audit.loadMore")}
          </button>
        )}
      </div>
    </>
  );
}
