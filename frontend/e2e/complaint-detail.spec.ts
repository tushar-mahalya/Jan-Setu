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

const detail = {
  id: "33333333-3333-4333-8333-333333333333",
  human_id: "JS-20260710-00001",
  category: "pothole_surface_damage",
  category_label: "Pothole or road surface damage",
  domain_label: "Roads & Mobility",
  status: "registered",
  priority: "normal",
  source: "web",
  created_at: "2026-07-10T10:00:00Z",
  address: "MG Road, Pune, Maharashtra",
  issue_text: "Large pothole near the bus stop has damaged two-wheelers.",
  department_key: "public_works",
  department_name: "Public Works Department",
  term: "long_term",
  confidence: 0.9,
  image_match_status: "matched",
  flags: [],
  report_count: 1,
  dispatch_ref: null,
  pdf_url: null,
  disposition: "municipal_ticket",
  review_status: "confirmed",
  transcript_metadata: [],
  voice_note_urls: [],
  structured_facts: { summary: "Large pothole near the MG Road bus stop is creating a road hazard." },
  routing: { owning_agency: "Demo Municipal Corporation", dispatch_enabled: false, sla_hours: 72 },
  events: [
    { status: "registered", note: null, created_at: "2026-07-10T10:05:00Z" },
    { status: "submitted", note: "Forwarded to Public Works Department", created_at: "2026-07-11T09:00:00Z" },
  ],
};

test("complaint detail shows a loading state before data arrives", async ({ page }) => {
  await mockCitizenAuth(page);
  await page.route(`**/api/grievances/${detail.id}`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fulfill({ json: detail });
  });
  const errors = await collectErrors(page);
  await page.goto(`/complaints/${detail.id}`);
  await expect(page.getByRole("status", { name: "Loading complaint" })).toBeVisible();
  await expect(page.locator(".detail-header").getByText("JS-20260710-00001")).toBeVisible();
  expect(errors).toEqual([]);
});

test("complaint detail renders grievance summary, status, and timeline", async ({ page }) => {
  await mockCitizenAuth(page);
  await page.route(`**/api/grievances/${detail.id}`, (route) => route.fulfill({ json: detail }));
  const errors = await collectErrors(page);
  await page.goto(`/complaints/${detail.id}`);
  await expect(page.getByRole("heading", { name: "Pothole or road surface damage" })).toBeVisible();
  await expect(page.locator(".detail-header").getByText("JS-20260710-00001")).toBeVisible();
  await expect(page.getByText("Registered", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("list", { name: "Complaint status updates" })).toBeVisible();
  await expect(page.getByText("Forwarded to Public Works Department")).toBeVisible();
  expect(errors).toEqual([]);
});

test("complaint detail back-to-dashboard link navigates to the dashboard", async ({ page }) => {
  await mockCitizenAuth(page);
  await page.route(`**/api/grievances/${detail.id}`, (route) => route.fulfill({ json: detail }));
  await page.route("**/api/grievances?**", (route) => route.fulfill({ json: [] }));
  const errors = await collectErrors(page);
  await page.goto(`/complaints/${detail.id}`);
  const backLink = page.getByRole("link", { name: "Back to dashboard" });
  await expect(backLink).toHaveAttribute("href", "/dashboard");
  await backLink.click();
  await expect(page).toHaveURL("/dashboard");
  expect(errors).toEqual([]);
});
