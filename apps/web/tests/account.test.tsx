import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountMenu, initials } from "../src/components/AccountMenu";
import { setLang } from "../src/i18n";

afterEach(() => setLang("en"));

describe("account menu", () => {
  it("makes initials from one or several words", () => {
    expect(initials("Nagar Saathi Administrator")).toBe("NA");
    expect(initials("saish")).toBe("S");
    expect(initials("  ")).toBe("?");
  });

  it("names the account and role on the button, opens a menu and signs out", () => {
    const signOut = vi.fn();
    render(<AccountMenu user={{ name: "Asha Rao", email: "asha@example.com", role: "admin" }} onSignOut={signOut} />);
    const button = screen.getByRole("button", { name: /Asha Rao, Administrator/ });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(screen.getByText("asha@example.com")).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign Out" }));
    expect(signOut).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes on Escape and on an outside press", () => {
    render(<AccountMenu user={{ name: "Ravi K", role: "citizen" }} onSignOut={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Ravi K, Citizen/ }));
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Ravi K, Citizen/ }));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
