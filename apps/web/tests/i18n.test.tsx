import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";
import { describePlace } from "../src/geocode";
import { setLang, translate } from "../src/i18n";
import { en, kn } from "../src/i18n/strings";

afterEach(() => {
  setLang("en");
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("language switch", () => {
  it("switches the interface to Kannada and back, and remembers the choice", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({}),
        text: async () => "{}",
      })),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getAllByText("Overview").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "ಕನ್ನಡ" }));
    expect(await screen.findAllByText(kn["nav.Overview"])).not.toHaveLength(0);
    expect(document.documentElement.lang).toBe("kn");
    expect(localStorage.getItem("nagarsaathi.lang")).toBe("kn");

    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(await screen.findAllByText("Overview")).not.toHaveLength(0);
  });

  it("has a Kannada string for every English key and fills placeholders", () => {
    expect(Object.keys(kn).sort()).toEqual(Object.keys(en).sort());
    expect(translate("kn", "toast.signedInAs", { name: "Asha" })).toContain("Asha");
  });
});

describe("nearby landmark", () => {
  it("builds a short landmark from a reverse-geocode result", () => {
    expect(
      describePlace({
        name: "Forum Mall",
        address: { road: "Hosur Road", suburb: "Koramangala", city: "Bengaluru" },
      }),
    ).toBe("Forum Mall, Hosur Road, Koramangala");
    expect(describePlace({ address: { road: "80 Feet Road", neighbourhood: "Koramangala 4th Block" } })).toBe(
      "80 Feet Road, Koramangala 4th Block",
    );
    expect(describePlace({ error: "Unable to geocode" })).toBeNull();
  });
});
