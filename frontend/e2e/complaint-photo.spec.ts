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

// A minimal valid 1x1 transparent PNG, used as a photo-upload fixture.
const onePixelPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

const draftWithPhoto = {
  id: "55555555-5555-4555-8555-555555555555",
  human_id: "JS-20260716-00003",
  status: "awaiting_confirmation",
  category: "pothole_surface_damage",
  category_id: "pothole_surface_damage",
  category_label: "Pothole or road surface damage",
  domain_label: "Roads & Mobility",
  department_name: "Public Works Department",
  priority: "normal",
  term: "long_term",
  confidence: 0.92,
  address: "MG Road, Pune, Maharashtra",
  issue_text: "Large pothole near the bus stop has damaged two-wheelers.",
  image_match_status: "matched",
  flags: [],
  pdf_url: null,
  taxonomy_version: "2026-07-v2",
  safety_level: "none",
  asset_scope: "public",
  disposition: "municipal_ticket",
  review_status: "citizen_review",
  structured_facts: {
    summary: "Large pothole near the MG Road bus stop is creating a road hazard.",
    owner_hint: "ulb",
    missing_facts: [],
    clarification_question: null,
    contradictions: [],
    image_observations: ["Road surface cavity visible"],
  },
  routing: { owning_agency: "Demo Municipal Corporation", dispatch_enabled: false, sla_hours: 72 },
};

async function mockCitizenAuth(page: Page) {
  await page.route("**/auth/refresh", (route) => route.fulfill({ json: { access_token: tokenPayload({ sub: "citizen" }) } }));
}

test("new complaint flow reaches review after attaching a photo", async ({ page }) => {
  await mockCitizenAuth(page);
  await page.route("**/api/grievances/draft", (route) => route.fulfill({ json: draftWithPhoto }));
  const errors = await collectErrors(page);
  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation({ latitude: 18.5204, longitude: 73.8567 });
  await page.goto("/complaints/new");
  await page.getByRole("button", { name: /Use my location/i }).click();
  await page.getByRole("button", { name: /Continue/i }).click();
  await page.getByLabel("Describe the civic issue").fill("Large pothole near the bus stop has damaged two-wheelers.");
  await page.getByRole("button", { name: /Continue/i }).click();
  await page.locator('input[type="file"]').setInputFiles({ name: "photo.png", mimeType: "image/png", buffer: onePixelPng });
  await expect(page.getByRole("button", { name: "Change" })).toBeVisible();
  await page.getByRole("button", { name: "Review complaint →" }).click();
  await expect(page.getByRole("heading", { name: "Review what we understood" })).toBeVisible();
  await expect(page.getByText("Pothole or road surface damage")).toBeVisible();
  expect(errors).toEqual([]);
});
