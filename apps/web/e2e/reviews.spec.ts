import { test, expect } from "@playwright/test";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAE0lEQVR4nGP8z4APMOGVZRip0gBBLAETee26JgAAAABJRU5ErkJggg==",
  "base64",
);
test("provisioned staff reviews real evidence and category", async ({
  page,
  request,
}) => {
  const owner = { Authorization: "Bearer demo-citizen" };
  const upload = await request.post("/api/v1/uploads", {
    headers: { ...owner, "Content-Type": "image/png" },
    data: png,
  });
  const media = await upload.json();
  expect(upload.status()).toBe(201);
  await request.post(`/api/v1/uploads/${media.id}/complete`, {
    headers: owner,
  });
  const response = await request.post("/api/v1/reports", {
    headers: { ...owner, "Idempotency-Key": crypto.randomUUID() },
    data: {
      description: `Staff journey ${crypto.randomUUID()}`,
      claimed_category: "pothole",
      media_ids: [media.id],
      location: { longitude: 77.615, latitude: 12.915, confirmed: true },
    },
  });
  const report = await response.json();
  expect(response.status()).toBe(201);
  await page.goto(`/reviews/${report.id}`);
  await page.getByText("Use a provisioned identity token").click();
  await page
    .getByLabel("Identity token", { exact: true })
    .fill("demo-reviewer");
  await page.getByRole("button", { name: "Sign in with token" }).click();
  await expect(
    page.getByRole("img", { name: "Review evidence 1" }),
  ).toBeVisible();
  await page
    .getByLabel("Confirmed category")
    .selectOption("garbage_accumulation");
  await page
    .getByLabel("Decision reason")
    .fill("Synthetic staff-reviewed garbage evidence");
  await page
    .getByRole("button", { name: "Accept evidence and category" })
    .click();
  await expect(page.getByText(/Current validation: accepted/)).toBeVisible();
  const current = await request.get(`/api/v1/reports/${report.id}`, {
    headers: owner,
  });
  expect((await current.json()).canonical_category).toBe(
    "garbage_accumulation",
  );
  await page.screenshot({
    path: `.local/qa/cp4-${test.info().project.name}.png`,
    fullPage: true,
  });
});
