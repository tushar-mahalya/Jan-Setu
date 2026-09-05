import { expect, test, type Page } from "@playwright/test";

function tokenPayload(payload: Record<string, unknown>) {
  return `x.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.x`;
}

// These tests deliberately mock 500 responses, which makes Chromium log a
// benign "Failed to load resource" console.error for the failed network
// request itself — that's expected noise, not an app bug. So unlike the
// other specs, only uncaught exceptions (real crashes) are tracked here.
async function collectCrashes(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`page:${error.message}`));
  return errors;
}

async function mockCitizenAuth(page: Page) {
  await page.route("**/auth/refresh", (route) => route.fulfill({ json: { access_token: tokenPayload({ sub: "citizen" }) } }));
}

test("dashboard shows a recoverable error when the grievance list fails", async ({ page }) => {
  await mockCitizenAuth(page);
  await page.route("**/api/grievances?**", (route) => route.fulfill({ status: 500, json: { detail: "Internal server error" } }));
  const errors = await collectCrashes(page);
  await page.goto("/dashboard");
  await expect(page.getByText("We couldn’t load your complaints.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("new complaint shows a user-facing error when draft creation fails", async ({ page }) => {
  await mockCitizenAuth(page);
  await page.route("**/api/grievances/draft", (route) => route.fulfill({ status: 500, json: { detail: "Could not create draft" } }));
  const errors = await collectCrashes(page);
  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation({ latitude: 18.5204, longitude: 73.8567 });
  await page.goto("/complaints/new");
  await page.getByRole("button", { name: /Use my location/i }).click();
  await page.getByRole("button", { name: /Continue/i }).click();
  await page.getByLabel("Describe the civic issue").fill("Large pothole near the bus stop has damaged two-wheelers.");
  await page.getByRole("button", { name: /Continue/i }).click();
  await page.getByRole("button", { name: /Continue without a photo/i }).click();
  await expect(page.getByRole("alert")).toContainText("Could not create draft");
  await expect(page.getByRole("heading", { name: "Review what we understood" })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("citizen sign-in surfaces an error when the WhatsApp approval check fails", async ({ page }) => {
  const verification = {
    verification_id: "66666666-6666-4666-8666-666666666666",
    method: "whatsapp_approval",
    wa_link: "https://wa.me/910000000000?text=approve",
    expires_at: new Date(Date.now() + 600_000).toISOString(),
  };
  await page.route("**/auth/request-code", (route) => route.fulfill({ json: verification }));
  await page.route("**/auth/approval-status", (route) => route.fulfill({ status: 500, json: { detail: "Could not check approval" } }));
  const errors = await collectCrashes(page);
  await page.goto("/login");
  await page.getByLabel("WhatsApp phone number").fill("+91 98765 43210");
  await page.getByRole("button", { name: "Continue securely →" }).click();
  await expect(page.getByRole("heading", { name: "Check your Jan Setu chat" })).toBeVisible();
  await expect(page.getByText("Could not check approval just now. Keep this page open; Jan Setu will retry.")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
  expect(errors).toEqual([]);
});
