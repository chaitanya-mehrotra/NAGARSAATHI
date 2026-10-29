import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";

function reply(data: unknown) {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

/** Stub the API by path; anything unlisted answers an empty object. */
function stubApi(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const match = Object.keys(routes).find((path) => url.includes(path));
      return reply(match ? routes[match] : {});
    }),
  );
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("dashboard", () => {
  it("shows the API's real counts instead of the list total", async () => {
    stubApi({
      "/api/v1/auth/options": { google_client_id: null, demo_enabled: false },
      "/api/v1/metrics": {
        reports: { total: 6, admitted: 0, rejected: 0, pending: 6, suspicious: 4 },
        issues: { total: 0, resolved: 0, active: 0 },
        categories: { pothole: 3, waterlogging: 1 },
      },
      "/api/v1/complaints": { items: [], total: 0 },
    });
    renderApp();
    const tile = (await screen.findByText("Pothole reports")).closest("button")!;
    await vi.waitFor(() => expect(tile).toHaveTextContent("3"));
    const waterlogging = screen.getByText("Waterlogging reports").closest("button")!;
    expect(waterlogging).toHaveTextContent("1");
  });

  it("invites signed-out visitors to sign in instead of showing an auth error", async () => {
    stubApi({
      "/api/v1/auth/options": { google_client_id: null, demo_enabled: false },
      "/api/v1/metrics": {
        reports: { total: 10 },
        issues: {},
        categories: { pothole: 5 },
        stages: { awaiting_review: 7, out_of_scope: 3 },
      },
    });
    renderApp();
    expect(await screen.findByText(/Sign in to see the reports/)).toBeInTheDocument();
    expect(screen.queryByText(/bearer/i)).not.toBeInTheDocument();
    // Public counters still load without an account.
    const tile = screen.getByText("Pothole reports").closest("button")!;
    await vi.waitFor(() => expect(tile).toHaveTextContent("5"));
  });

  it("counts each stage the same way the list filters it", async () => {
    stubApi({
      "/api/v1/auth/options": { google_client_id: null, demo_enabled: false },
      "/api/v1/metrics": {
        reports: { total: 10 },
        issues: {},
        categories: {},
        stages: { awaiting_review: 7, out_of_scope: 3 },
      },
    });
    renderApp();
    const underReview = (await screen.findAllByText("Under review"))
      .map((el) => el.closest("button"))
      .find((b) => b?.closest(".status-items"))!;
    await vi.waitFor(() => expect(underReview).toHaveTextContent("7"));
    const outOfScope = screen
      .getAllByText("Out of scope")
      .map((el) => el.closest("button"))
      .find((b) => b?.closest(".status-items"))!;
    expect(outOfScope).toHaveTextContent("3");
  });

  it("reports a backend failure instead of showing invented complaints", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    renderApp();
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((alert) => /offline/.test(alert.textContent ?? ""))).toBe(true);
    expect(screen.queryByText(/Silk Board/)).not.toBeInTheDocument();
  });
});

describe("sign-in dialog", () => {
  async function openDialog() {
    renderApp();
    const [signIn] = await screen.findAllByRole("button", { name: /^Sign In$/ });
    fireEvent.click(signIn);
  }

  it("offers demo accounts only when the server enables demo mode", async () => {
    stubApi({
      "/api/v1/auth/options": { google_client_id: "client.apps.googleusercontent.com", demo_enabled: true },
      "/api/v1/complaints": { items: [], total: 0 },
    });
    await openDialog();
    expect(await screen.findByRole("button", { name: "Demo Accounts" })).toBeInTheDocument();
  });

  it("hides demo accounts and says so when Google is not configured", async () => {
    stubApi({
      "/api/v1/auth/options": { google_client_id: null, demo_enabled: false },
      "/api/v1/complaints": { items: [], total: 0 },
    });
    await openDialog();
    expect(await screen.findByText(/Google sign-in is not configured/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Demo Accounts" })).not.toBeInTheDocument();
  });
});
