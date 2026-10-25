import { test, expect } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";

let worker: ChildProcess;
test.beforeAll(() => {
  worker = spawn(path.resolve(".venv/Scripts/python.exe"), ["-m", "worker"], {
    windowsHide: true,
    stdio: "ignore",
  });
});
test.afterAll(() => {
  worker.kill();
});

test("staff filters, matching map order, Kannada evidence and assignment", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const citizen = { Authorization: "Bearer demo-citizen" };
  const admin = { Authorization: "Bearer demo-admin" };
  let lon = 0,
    lat = 0;
  for (let attempt = 0; attempt < 30; attempt++) {
    lon = 77.601 + Math.random() * 0.025;
    lat = 12.902 + Math.random() * 0.025;
    const empty = await request.get("/api/v1/staff/queue", {
      headers: admin,
      params: {
        area: "southwest",
        category: "pothole",
        bbox: `${lon - 0.0001},${lat - 0.0001},${lon + 0.0011},${lat + 0.0001}`,
      },
    });
    expect(empty.status()).toBe(200);
    if ((await empty.json()).total_issues === 0) break;
    if (attempt === 29)
      throw new Error("Could not find an unused fixture neighbourhood");
  }
  const ids: string[] = [];
  for (let n = 0; n < 2; n++) {
    const png = Buffer.concat([
      Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAE0lEQVR4nGP8z4APMOGVZRip0gBBLAETee26JgAAAABJRU5ErkJggg==",
        "base64",
      ),
      Buffer.from(crypto.randomUUID()),
    ]);
    const uploaded = await request.post("/api/v1/uploads", {
      headers: { ...citizen, "Content-Type": "image/png" },
      data: png,
    });
    expect(uploaded.status()).toBe(201);
    const media = await uploaded.json();
    await request.post(`/api/v1/uploads/${media.id}/complete`, {
      headers: citizen,
    });
    const submitted = await request.post("/api/v1/reports", {
      headers: { ...citizen, "Idempotency-Key": crypto.randomUUID() },
      data: {
        description: `ರಸ್ತೆಯಲ್ಲಿ ಗುಂಡಿ ಇದೆ ${crypto.randomUUID()}`,
        claimed_category: "pothole",
        media_ids: [media.id],
        location: {
          longitude: lon + n * 0.001,
          latitude: lat,
          confirmed: true,
        },
      },
    });
    expect(submitted.status()).toBe(201);
    const report = await submitted.json();
    const reviewed = await request.post(
      `/api/v1/reviews/${report.id}/decision`,
      {
        headers: admin,
        data: {
          request_id: crypto.randomUUID(),
          expected_revision: report.content_revision,
          category: "pothole",
          decision: "accepted",
          reason: "Inspected synthetic staff queue evidence",
        },
      },
    );
    expect(reviewed.status()).toBe(200);
    const created = await request.post(
      `/api/v1/reviews/duplicates/${report.id}/decision`,
      {
        headers: admin,
        data: {
          request_id: crypto.randomUUID(),
          expected_revision: (await reviewed.json()).content_revision,
          action: "new",
          reason: "Confirmed separate defect for staff queue test",
        },
      },
    );
    expect([200, 409]).toContain(created.status());
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get(`/api/v1/reports/${report.id}`, {
                headers: citizen,
              })
            ).json()
          ).issue_id,
        { timeout: 20000 },
      )
      .toBeTruthy();
    ids.push(
      (
        await (
          await request.get(`/api/v1/reports/${report.id}`, {
            headers: citizen,
          })
        ).json()
      ).issue_id,
    );
  }
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(`/api/v1/issues/${ids[0]}`, { headers: admin })
          ).json()
        ).priority,
      { timeout: 20000 },
    )
    .toBeTruthy();
  const bounds = `${lon - 0.0001},${lat - 0.0001},${lon + 0.0011},${lat + 0.0001}`;
  await page.goto(`/staff?area=southwest&category=pothole&bbox=${bounds}`);
  await page.getByText("Use a provisioned identity token").click();
  await page.getByLabel("Identity token", { exact: true }).fill("demo-admin");
  await page.getByRole("button", { name: "Sign in with token" }).click();
  await expect(page.locator(".queue-entry")).toHaveCount(2);
  await expect(page.locator(".queue-marker")).toHaveCount(2);
  const list = await page
    .locator(".queue-entry")
    .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-issue-id")));
  const pins = await page
    .locator(".queue-marker")
    .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-issue-id")));
  expect(pins).toEqual(list);
  const backend = await (
    await request.get(
      `/api/v1/staff/queue?area=southwest&category=pothole&bbox=${bounds}`,
      { headers: admin },
    )
  ).json();
  expect(
    backend.items.map((v: { issue: { id: string } }) => v.issue.id),
  ).toEqual(list);
  await expect(
    page.getByText(
      `${backend.total_issues} issues · ${backend.total_linked_reports} linked reports`,
      { exact: true },
    ),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `.local/qa/cp7-${test.info().project.name}.png`,
    fullPage: true,
  });
  const filteredUrl = page.url();
  await page.locator(".queue-entry h2 a").first().click();
  await expect(
    page.getByRole("heading", { name: /ರಸ್ತೆಯಲ್ಲಿ ಗುಂಡಿ ಇದೆ/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Priority explanation" }),
  ).toBeVisible();
  const operator = await page
    .getByLabel("Assigned operator")
    .locator("option")
    .nth(1)
    .getAttribute("value");
  await page.getByLabel("Assigned operator").selectOption(operator!);
  await page.getByLabel("Team label (optional)").fill("Road maintenance");
  await page
    .getByLabel("Assignment reason")
    .fill("Assign scoped operator after evidence review");
  await page.getByRole("button", { name: "Save assignment" }).click();
  await expect(
    page.getByText(/pothole · southwest · assigned · version/),
  ).toBeVisible();
  await page.getByRole("link", { name: "Back to work queue" }).click();
  expect(new URL(page.url()).searchParams.toString()).toBe(
    new URL(filteredUrl).searchParams.toString(),
  );
  await page
    .getByRole("combobox", { name: "Status", exact: true })
    .selectOption("assigned");
  await expect(page.locator(".queue-entry")).toHaveCount(1);
  await page.getByRole("link", { name: "Compare service areas" }).click();
  await expect(
    page.getByRole("heading", { name: "Service area overview" }),
  ).toBeVisible();
  const repairedId = list[0]!;
  async function signInWork(token: string) {
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.goto(`/work/${repairedId}`);
    await page.getByText("Use a provisioned identity token").click();
    await page.getByLabel("Identity token", { exact: true }).fill(token);
    await page.getByRole("button", { name: "Sign in with token" }).click();
  }
  await signInWork("demo-operator");
  await page
    .getByLabel("Work action reason")
    .fill("Starting assigned repair after site inspection");
  await page.getByRole("button", { name: "Start work", exact: true }).click();
  await expect(page.getByText(/in_progress · version/)).toBeVisible();
  await page.getByLabel("Repair photo").setInputFiles({
    name: "repair.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAE0lEQVR4nGP8z4APMOGVZRip0gBBLAETee26JgAAAABJRU5ErkJggg==",
      "base64",
    ),
  });
  await page
    .getByLabel("Work action reason")
    .fill("Repair completed and photographed at the site");
  await page
    .getByRole("button", { name: "Submit repair for verification" })
    .click();
  await expect(page.getByText(/resolution_pending · version/)).toBeVisible();
  await signInWork("demo-admin");
  await expect(page.getByAltText("Repair evidence")).toBeVisible();
  await page
    .getByLabel("Work action reason")
    .fill("Independent reviewer checked completed repair");
  await page
    .getByRole("button", { name: "Verify repair", exact: true })
    .click();
  await expect(page.getByText(/resolved · version/)).toBeVisible();
  await page
    .getByLabel("Work action reason")
    .fill("Verified issue archived while retaining all evidence");
  await page.getByRole("button", { name: "Archive issue" }).click();
  await expect(page.getByText(/Archived; evidence retained/)).toBeVisible();
  await page
    .getByLabel("Work action reason")
    .fill("Inspection found repair failure; reopen the same defect");
  await page.getByRole("button", { name: "Reopen issue" }).click();
  await expect(page.getByText(/reopened · version/)).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("empty queue and failed map retain usable filters and list", async ({
  page,
}) => {
  await page.route("**/api/v1/config/boundaries", (route) =>
    route.fulfill({ status: 503, body: "Unavailable" }),
  );
  await page.goto("/staff?area=northeast&bbox=0,0,0.001,0.001");
  await page.getByText("Use a provisioned identity token").click();
  await page.getByLabel("Identity token", { exact: true }).fill("demo-admin");
  await page.getByRole("button", { name: "Sign in with token" }).click();
  await expect(page.getByText("No issues match these filters.")).toBeVisible();
  await expect(
    page.getByText(/Map unavailable. The ranked list remains usable./),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Refresh ranking" }),
  ).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
