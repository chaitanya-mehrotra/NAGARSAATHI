import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { App } from "../src/App";

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

describe("pilot scaffold", () => {
  it("renders categories from the API and marks the demo honestly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          pilot: { service_areas: ["Southwest", "Northeast"] },
          categories: [
            {
              code: "pothole",
              label: "Pothole",
              requires_manual_categorisation: false,
            },
          ],
        }),
      }),
    );
    renderApp();
    expect(await screen.findByText("Pothole")).toBeInTheDocument();
    expect(screen.getByText("Development demo")).toBeInTheDocument();
    expect(screen.getByText(/does not submit complaints/)).toBeInTheDocument();
    expect(screen.getByText("Southwest")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /submit/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps coverage and a retry action available when the API fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    renderApp();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not be loaded/,
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Southeast Bengaluru" }),
    ).toBeInTheDocument();
  });
});
