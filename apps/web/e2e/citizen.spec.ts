import { test, expect } from "@playwright/test";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAE0lEQVR4nGP8z4APMOGVZRip0gBBLAETee26JgAAAABJRU5ErkJggg==",
  "base64",
);
async function start(page: import("@playwright/test").Page) {
  await page.goto("/report/new");
  await page.getByRole("button", { name: "Continue as demo citizen" }).click();
  await expect(page.getByLabel("Describe the problem")).toBeVisible();
}
async function fill(page: import("@playwright/test").Page, text: string) {
  await page
    .getByLabel("Photos (JPEG")
    .setInputFiles({ name: "no-exif.png", mimeType: "image/png", buffer: png });
  await page.getByLabel("Describe the problem").fill(text);
  await page.getByLabel("Longitude", { exact: true }).fill("77.615");
  await page.getByLabel("Latitude", { exact: true }).fill("12.915");
  await page.getByLabel("I confirm this pin").check();
}
test("submit, receipt, reload, my reports and private photo", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await start(page);
  const description = `Browser journey ${crypto.randomUUID()}`;
  await fill(page, description);
  await page
    .getByRole("button", { name: "Review report", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review before submitting" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Submit report", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Report received" }),
  ).toBeVisible();
  await expect(page.getByText(description, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(description, { exact: true })).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Submitted evidence 1" }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "My reports", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "My reports", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(description, { exact: true })).toBeVisible();
  await expect(page.locator("body")).not.toHaveJSProperty("scrollWidth", 2000);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  );
  expect(overflow).toBe(false);
  expect(errors).toEqual([]);
  await page.screenshot({
    path: `.local/qa/cp3-${test.info().project.name}.png`,
    fullPage: true,
  });
});

test("map failure retains coordinate input and draft reload", async ({
  page,
}) => {
  await page.route("**/api/v1/config/boundaries", (route) => route.abort());
  await start(page);
  await page
    .getByLabel("Describe the problem")
    .fill("Saved metadata after reload");
  await expect(
    page.getByText("Map unavailable. Enter coordinates below."),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Describe the problem")).toHaveValue(
    "Saved metadata after reload",
  );
  await expect(page.getByLabel("Longitude", { exact: true })).toBeVisible();
});
test("denied location, validation labels and upload retry preserve draft", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "geolocation", {
      value: {
        getCurrentPosition: (
          _success: unknown,
          error: (error: unknown) => void,
        ) => error({ code: 1 }),
      },
    });
  });
  await start(page);
  await page.getByRole("button", { name: "Use my location" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Location permission denied",
  );
  await page
    .getByRole("button", { name: "Review report", exact: true })
    .click();
  await expect(page.locator("#description-error")).toBeVisible();
  await fill(page, "Draft survives failed upload");
  let fails = 0;
  await page.route("**/api/v1/uploads", async (route) => {
    if (fails++ === 0)
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ message: "Upload offline" }),
      });
    else await route.continue();
  });
  await page
    .getByRole("button", { name: "Review report", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Upload offline");
  await expect(page.getByLabel("Describe the problem")).toHaveValue(
    "Draft survives failed upload",
  );
  await page
    .getByRole("button", { name: "Review report", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review before submitting" }),
  ).toBeVisible();
});
test("keyboard-only metadata and repeated submission request", async ({
  page,
}) => {
  await start(page);
  await fill(page, `Keyboard ${crypto.randomUUID()}`);
  await page.getByLabel("Address or landmark").focus();
  await page.keyboard.type("Offline landmark");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("I confirm this pin")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByLabel("Does this look like an existing nearby issue?"),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Review report", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: "Submit report", exact: true }),
  ).toBeVisible();
  let returned = "";
  await page.route("**/api/v1/reports", async (route) => {
    const response = await route.fetch();
    returned = await response.text();
    const repeated = await route.fetch();
    expect(await repeated.text()).toBe(returned);
    await route.fulfill({ response, body: returned });
  });
  await page
    .getByRole("button", { name: "Submit report", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Report received" }),
  ).toBeVisible();
});
