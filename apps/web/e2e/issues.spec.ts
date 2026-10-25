import { test, expect, type APIRequestContext } from "@playwright/test";
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

async function accepted(
  request: APIRequestContext,
  longitude: number,
  latitude: number,
) {
  const owner = { Authorization: "Bearer demo-citizen" };
  const png = Buffer.concat([
    Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAE0lEQVR4nGP8z4APMOGVZRip0gBBLAETee26JgAAAABJRU5ErkJggg==",
      "base64",
    ),
    Buffer.from(crypto.randomUUID()),
  ]);
  const uploaded = await request.post("/api/v1/uploads", {
    headers: { ...owner, "Content-Type": "image/png" },
    data: png,
  });
  expect(uploaded.status()).toBe(201);
  const media = await uploaded.json();
  await request.post(`/api/v1/uploads/${media.id}/complete`, {
    headers: owner,
  });
  const response = await request.post("/api/v1/reports", {
    headers: { ...owner, "Idempotency-Key": crypto.randomUUID() },
    data: {
      description: `Shared issue journey ${crypto.randomUUID()}`,
      claimed_category: "pothole",
      media_ids: [media.id],
      location: { longitude, latitude, confirmed: true },
    },
  });
  expect(response.status()).toBe(201);
  const report = await response.json();
  const reviewed = await request.post(`/api/v1/reviews/${report.id}/decision`, {
    headers: { Authorization: "Bearer demo-admin" },
    data: {
      request_id: crypto.randomUUID(),
      expected_revision: report.content_revision,
      decision: "accepted",
      category: "pothole",
      reason: "Inspected synthetic photo and confirmed issue pin",
    },
  });
  expect(reviewed.status()).toBe(200);
  await expect
    .poll(
      async () => {
        const current = await (
          await request.get(`/api/v1/reports/${report.id}`, { headers: owner })
        ).json();
        return current.issue_id || current.review_reason;
      },
      { timeout: 20000 },
    )
    .not.toBe("Inspected synthetic photo and confirmed issue pin");
  return (
    await request.get(`/api/v1/reports/${report.id}`, { headers: owner })
  ).json();
}

test("staff links, creates, merges and splits without losing reports", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  let longitude = 0,
    latitude = 0;
  for (let attempt = 0; attempt < 20; attempt++) {
    longitude = 77.667 + Math.random() * 0.021;
    latitude = 12.933 + Math.random() * 0.024;
    const nearby = await request.get(
      `/api/v1/issues/nearby?longitude=${longitude}&latitude=${latitude}&category=pothole`,
      { headers: { Authorization: "Bearer demo-citizen" } },
    );
    expect(nearby.status()).toBe(200);
    if ((await nearby.json()).length === 0) break;
  }
  const first = await accepted(request, longitude, latitude);
  expect(first.state).toBe("admitted");
  const second = await accepted(request, longitude + 0.00005, latitude);
  expect(second.state).toBe("awaiting_review");
  await page.goto("/reviews/duplicates");
  await page.getByText("Use a provisioned identity token").click();
  await page.getByLabel("Identity token", { exact: true }).fill("demo-admin");
  await page.getByRole("button", { name: "Sign in with token" }).click();
  const card = page.locator(".duplicate-card").filter({
    has: page.getByRole("heading", { name: second.description, exact: true }),
  });
  await card
    .getByLabel("Existing issue candidate")
    .selectOption(first.issue_id);
  await expect(
    card.getByRole("img", { name: "Comparison evidence 1" }).first(),
  ).toBeVisible();
  await card
    .getByLabel("Comparison reason")
    .fill("Verified the same physical pothole from two separate photos");
  await card
    .getByRole("button", { name: "Link to existing issue", exact: true })
    .click();
  await expect(card).toHaveCount(0);
  const third = await accepted(request, longitude + 0.00008, latitude);
  await page.getByRole("button", { name: "Reload candidates" }).click();
  const separate = page.locator(".duplicate-card").filter({
    has: page.getByRole("heading", { name: third.description, exact: true }),
  });
  await separate
    .getByLabel("Comparison reason")
    .fill("Reviewed a distinct adjacent defect, keep a separate repair task");
  await separate.getByRole("button", { name: "Create separate issue" }).click();
  await expect(separate).toHaveCount(0);
  const current = await (
    await request.get(`/api/v1/reports/${third.id}`, {
      headers: { Authorization: "Bearer demo-citizen" },
    })
  ).json();
  await page.goto(`/issues/${current.issue_id}`);
  const targetIssue = await (
    await request.get(`/api/v1/issues/${first.issue_id}`, {
      headers: { Authorization: "Bearer demo-admin" },
    })
  ).json();
  await page
    .getByLabel("Find merge target by exact issue reference")
    .fill(targetIssue.public_reference);
  await page
    .getByLabel("Merge into existing issue")
    .selectOption(first.issue_id);
  await page
    .getByLabel("Change reason")
    .fill("Further review confirmed the adjacent photographs show one pothole");
  await page.getByRole("button", { name: "Merge and retain history" }).click();
  await expect(
    page.getByRole("link", { name: "Open surviving issue" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Open surviving issue" }).click();
  await expect(page.getByText(/3 linked reports/)).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Select for split" })
    .first()
    .check();
  await page.getByLabel("Split longitude").fill(String(longitude + 0.0001));
  await page
    .getByLabel("Change reason")
    .fill("Detailed inspection distinguished the selected physical defect");
  await page.getByRole("button", { name: "Split selected reports" }).click();
  await expect(page.getByText(/2 linked reports/)).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: `.local/qa/cp5-${test.info().project.name}.png`,
    fullPage: true,
  });
});
