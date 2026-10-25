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

test("review priority and activate a complete policy preview", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const citizen = { Authorization: "Bearer demo-citizen" };
  const admin = { Authorization: "Bearer demo-admin" };
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
  const reported = await request.post("/api/v1/reports", {
    headers: { ...citizen, "Idempotency-Key": crypto.randomUUID() },
    data: {
      description: `Priority journey ${crypto.randomUUID()}`,
      claimed_category: "pothole",
      media_ids: [media.id],
      reported_hazard: true,
      location: {
        longitude: 77.613 + Math.random() * 0.01,
        latitude: 12.903 + Math.random() * 0.01,
        confirmed: true,
      },
    },
  });
  expect(reported.status()).toBe(201);
  const report = await reported.json();
  const reviewed = await request.post(`/api/v1/reviews/${report.id}/decision`, {
    headers: admin,
    data: {
      request_id: crypto.randomUUID(),
      expected_revision: report.content_revision,
      category: "pothole",
      decision: "accepted",
      reason: "Inspected priority fixture evidence and pin",
    },
  });
  expect(reviewed.status()).toBe(200);
  const created = await request.post(
    `/api/v1/reviews/duplicates/${report.id}/decision`,
    {
      headers: admin,
      data: {
        request_id: crypto.randomUUID(),
        expected_revision: (await reviewed.json()).content_revision,
        action: "new",
        reason: "Confirmed separate physical defect for priority test",
      },
    },
  );
  // Worker may already have admitted a candidate-free report.
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
  const current = await (
    await request.get(`/api/v1/reports/${report.id}`, { headers: citizen })
  ).json();
  await page.goto(`/issues/${current.issue_id}`);
  await page.getByText("Use a provisioned identity token").click();
  await page.getByLabel("Identity token", { exact: true }).fill("demo-admin");
  await page.getByRole("button", { name: "Sign in with token" }).click();
  await page.getByLabel("Severity override").selectOption("0.75");
  await page.getByLabel("Reviewed urgency").selectOption("1");
  await page.getByLabel("Confirm critical scheduling override").check();
  const localDeadline = new Date(Date.now() + 3600000);
  const localValue = new Date(
    localDeadline.getTime() - localDeadline.getTimezoneOffset() * 60000,
  )
    .toISOString()
    .slice(0, 16);
  await page.getByLabel("Critical review deadline").fill(localValue);
  await page
    .getByLabel("Priority decision reason")
    .fill("Reviewed immediate hazard and serious severity with evidence");
  await page.getByRole("button", { name: "Save priority review" }).click();
  await expect(page.getByText(/\/ 100 · critical/)).toBeVisible();
  await expect(
    page.getByText("location context unknown", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: `.local/qa/cp6-${test.info().project.name}.png`,
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Priority policies", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Preview scores" }),
  ).toBeVisible();
  await page
    .getByLabel("New policy version")
    .fill(`browser-priority-${crypto.randomUUID()}`);
  await page
    .getByLabel("Policy review reason")
    .fill(
      "Synthetic preview reviewed for stable scoring and explicit unknown context",
    );
  await page.getByRole("button", { name: "Create policy preview" }).click();
  await expect(
    page.getByRole("button", { name: "Activate reviewed preview" }),
  ).toBeVisible();
  await page
    .getByLabel("Policy review reason")
    .fill(
      "Reviewed unchanged demo weights and all active fixture score explanations",
    );
  await page.getByRole("button", { name: "Activate reviewed preview" }).click();
  await expect(
    page.getByRole("button", { name: "Activate reviewed preview" }),
  ).toHaveCount(0);
  const ranked = await request.get("/api/v1/priority/ranking", {
    headers: admin,
  });
  expect(ranked.status()).toBe(200);
  const priorities = (await ranked.json()).filter(
    (i: { priority: unknown }) => i.priority,
  );
  expect(
    new Set(
      priorities.map(
        (i: { priority: { epoch_id: string } }) => i.priority.epoch_id,
      ),
    ).size,
  ).toBe(1);
});
