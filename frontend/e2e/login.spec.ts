import { expect, test, type Page } from "@playwright/test";

function tokenPayload(payload: Record<string, unknown>) {
  return `x.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.x`;
}

async function collectErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`page:${error.message}`));
  page.on("console", (message) => { if (message.type() === "error") errors.push(`console:${message.text()}`); });
  return errors;
}

const verification = {
  verification_id: "44444444-4444-4444-8444-444444444444",
  method: "reverse_code",
  code: "482913",
  wa_link: "https://wa.me/910000000000?text=482913",
  expires_at: new Date(Date.now() + 600_000).toISOString(),
};

async function requestCode(page: Page) {
  await page.goto("/login");
  await page.getByLabel("WhatsApp phone number").fill("+91 98765 43210");
  await page.getByRole("button", { name: "Continue securely →" }).click();
}

test("submitting a phone number shows the WhatsApp verification code screen", async ({ page }) => {
  await page.route("**/auth/request-code", (route) => route.fulfill({ json: verification }));
  await page.route("**/auth/status**", (route) => route.fulfill({ json: { status: "pending" } }));
  const errors = await collectErrors(page);
  await requestCode(page);
  await expect(page.getByRole("heading", { name: "Send this exact code" })).toBeVisible();
  await expect(page.getByText("482913")).toBeVisible();
  expect(errors).toEqual([]);
});

test("a verified code navigates the citizen to the dashboard", async ({ page }) => {
  await page.route("**/auth/request-code", (route) => route.fulfill({ json: verification }));
  await page.route("**/auth/status**", (route) => route.fulfill({ json: { status: "verified", access_token: tokenPayload({ sub: "citizen" }) } }));
  await page.route("**/api/grievances?**", (route) => route.fulfill({ json: [] }));
  const errors = await collectErrors(page);
  await requestCode(page);
  await expect(page).toHaveURL("/dashboard", { timeout: 10_000 });
  await expect(page.getByRole("heading", { name: "Your complaints" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("a denied verification shows an error and stays on the login page", async ({ page }) => {
  await page.route("**/auth/request-code", (route) => route.fulfill({ json: verification }));
  await page.route("**/auth/status**", (route) => route.fulfill({ json: { status: "denied" } }));
  const errors = await collectErrors(page);
  await requestCode(page);
  await expect(page.getByRole("heading", { name: "Your account remains protected" })).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
  expect(errors).toEqual([]);
});
