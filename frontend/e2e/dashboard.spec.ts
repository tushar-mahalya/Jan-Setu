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

async function mockCitizenAuth(page: Page) {
  await page.route("**/auth/refresh", (route) => route.fulfill({ json: { access_token: tokenPayload({ sub: "citizen" }) } }));
}

const grievances = [
  { id: "aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaa1", human_id: "JS-20260710-00001", category: "pothole_surface_damage", status: "registered", priority: "normal", source: "web", created_at: "2026-07-10T10:00:00Z" },
  { id: "aaaaaaaa-2222-4aaa-8aaa-aaaaaaaaaaa2", human_id: "JS-20260711-00002", category: "streetlight_out", status: "submitted", priority: "high", source: "whatsapp", created_at: "2026-07-11T11:00:00Z" },
];

test("dashboard shows loading state then empty state", async ({ page }) => {
  await mockCitizenAuth(page);
  await page.route("**/api/grievances?**", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fulfill({ json: [] });
  });
  const errors = await collectErrors(page);
  await page.goto("/dashboard");
  await expect(page.getByRole("status", { name: "Loading complaints" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your neighbourhood starts here" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("dashboard renders populated grievances and navigates on row click", async ({ page }) => {
  await mockCitizenAuth(page);
  await page.route("**/api/grievances?**", (route) => route.fulfill({ json: grievances }));
  await page.route(`**/api/grievances/${grievances[0].id}`, (route) => route.fulfill({
    json: { ...grievances[0], address: "MG Road, Pune", issue_text: "Pothole", department_key: "public_works", department_name: "Public Works Department", term: "long_term", confidence: 0.9, image_match_status: "matched", flags: [], report_count: 1, dispatch_ref: null, events: [], pdf_url: null, transcript_metadata: [], voice_note_urls: [] },
  }));
  const errors = await collectErrors(page);
  await page.goto("/dashboard");
  await expect(page.getByText("JS-20260710-00001")).toBeVisible();
  await expect(page.getByText("Pothole surface damage")).toBeVisible();
  await expect(page.getByText("JS-20260711-00002")).toBeVisible();
  await expect(page.getByText("Streetlight out")).toBeVisible();
  await expect(page.getByText("Registered")).toBeVisible();
  await expect(page.getByText("Submitted")).toBeVisible();
  await page.getByRole("row", { name: "Open complaint JS-20260710-00001" }).click();
  await expect(page).toHaveURL(`/complaints/${grievances[0].id}`);
  expect(errors).toEqual([]);
});
