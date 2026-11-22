import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Reports } from "../src/components/Reports";
import { setLang } from "../src/i18n";

const summary = {
  as_of: "2026-11-22T10:00:00+05:30",
  range: { since: "2026-11-20", until: "2026-11-22", granularity: "day" },
  filters: { category: null, area: null },
  totals: { reports: 5, flagged: 1 },
  by_status: { awaiting_review: 1, open: 2, in_progress: 1, resolved: 1, out_of_scope: 0, rejected: 0 },
  by_category: [{ category: "pothole", count: 4 }, { category: "waterlogging", count: 1 }],
  volume: [
    { bucket: "2026-11-20", total: 2, by_category: { pothole: 2 } },
    { bucket: "2026-11-21", total: 0, by_category: {} },
    { bucket: "2026-11-22", total: 3, by_category: { pothole: 2, waterlogging: 1 } },
  ],
  areas: [{ code: "southwest", name: "South West", count: 5, open: 3 }],
  photo_check: { checked: 4, unchecked: 1, accepted: 3, needs_review: 1, flagged: 1 },
  resolution: [{ category: "pothole", resolved: 1, median_hours: 12, p90_hours: 12, target_hours: 72, within_target: 1 }],
  backlog: [{ bucket: "0-2", count: 2 }, { bucket: "3-7", count: 1 }, { bucket: "8-30", count: 0 }, { bucket: "30+", count: 0 }],
  top_priorities: [],
};

afterEach(() => {
  setLang("en");
  vi.unstubAllGlobals();
});

function stub(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true, status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body, text: async () => JSON.stringify(body),
  })));
}

describe("reports page", () => {
  it("shows the scope, headline numbers and an honest empty list", async () => {
    stub(summary);
    render(<Reports />);
    expect(await screen.findByText("Reports received")).toBeTruthy();
    expect(screen.getByText("Reports over time")).toBeTruthy();
    expect(screen.getByText("No open repair tasks.")).toBeTruthy();
    expect(screen.getByText(/Data as of/)).toBeTruthy();
  });

  it("can show every chart as a table", async () => {
    stub(summary);
    render(<Reports />);
    fireEvent.click(await screen.findByText("Show as tables"));
    expect(screen.getAllByRole("table").length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText("Show charts")).toBeTruthy();
  });
});
