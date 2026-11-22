import { useEffect, useState } from "react";
import { request } from "../services";
import { useI18n } from "../i18n";

export type AuditEvent = {
  occurred_at: string;
  action: string;
  to_state?: string | null;
  from_state?: string | null;
  actor_name?: string | null;
  reason?: string | null;
  source?: string;
  report_id?: string | null;
  details?: Record<string, unknown> | null;
};

/** Plain-language name for an action; unknown actions fall back to a readable form of the code. */
export function useActionName() {
  const { t } = useI18n();
  return (action: string) => {
    const key = `audit.action.${action}`;
    const text = t(key);
    return text === key ? action.replace(/_/g, " ") : text;
  };
}

/** Oldest-first timeline of one report. Staff also see who acted and why; citizens never do. */
export function ReportHistory({ reportId }: { reportId: string }) {
  const { t, locale } = useI18n();
  const actionName = useActionName();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setEvents(null);
    setFailed(false);
    request(`/api/v1/reports/${reportId}/history`)
      .then((data) => active && setEvents(data?.events ?? []))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [reportId]);

  return (
    <section className="drawer-panel history-panel" aria-label={t("history.title")}>
      <div className="drawer-panel-head">
        <h3>{t("history.title")}</h3>
      </div>
      {failed ? (
        <p role="alert">{t("history.error")}</p>
      ) : events === null ? (
        <p>{t("history.loading")}</p>
      ) : events.length === 0 ? (
        <p>{t("history.empty")}</p>
      ) : (
        <ol className="timeline">
          {events.map((e, i) => (
            <li key={i}>
              <span className="timeline-dot" aria-hidden="true" />
              <div>
                <strong>{actionName(e.action)}</strong>
                {e.to_state && t(`status.${e.to_state}`) !== `status.${e.to_state}` && (
                  <span className="timeline-state"> → {t(`status.${e.to_state}`)}</span>
                )}
                <small>
                  {new Date(e.occurred_at).toLocaleString(locale)}
                  {e.actor_name ? " · " + t("history.by", { name: e.actor_name }) : ""}
                </small>
                {e.reason && <p className="timeline-reason">{e.reason}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
