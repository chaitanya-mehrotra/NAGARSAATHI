import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuditLog } from "../src/components/AuditLog";
import { ReportHistory } from "../src/components/History";
import { setLang } from "../src/i18n";

function stubApi(body: unknown) {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  setLang("en");
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("report history", () => {
  it("shows a readable timeline, with the reviewer only when the API sends one", async () => {
    stubApi({
      events: [
        { occurred_at: "2026-11-01T05:00:00Z", action: "report_submitted", to_state: "submitted" },
        { occurred_at: "2026-11-01T06:00:00Z", action: "status_override", to_state: "resolved", actor_name: "Admin A", reason: "Fixed on site" },
      ],
    });
    render(<ReportHistory reportId="r1" />);
    expect(await screen.findByText("Report submitted")).toBeTruthy();
    expect(screen.getByText("Status changed by staff")).toBeTruthy();
    expect(screen.getByText("Fixed on site")).toBeTruthy();
    expect(screen.getByText(/by Admin A/)).toBeTruthy();
  });

  it("reports a load failure instead of an empty history", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<ReportHistory reportId="r1" />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});

describe("audit log", () => {
  it("lists events newest first and offers older ones", async () => {
    const fetchMock = stubApi({
      events: [
        { occurred_at: "2026-11-02T05:00:00Z", source: "moderation", action: "soft_delete", actor_name: "Admin A", report_id: "abcdef12-0000", reason: "Spam" },
      ],
      next_before: "2026-11-02T05:00:00Z",
    });
    render(<AuditLog />);
    expect(await screen.findByText("Complaint deleted")).toBeTruthy();
    expect(screen.getByText("Spam")).toBeTruthy();
    expect(screen.getByText("Load older events")).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain("/api/v1/audit?limit=50");
  });
});
