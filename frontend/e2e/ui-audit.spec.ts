import { expect, test, type Page } from "@playwright/test";

const citizenDraft = {
  id: "11111111-1111-4111-8111-111111111111",
  human_id: "JS-20260715-00001",
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

async function openReview(page: Page) {
  await mockCitizenAuth(page);
  await page.route("**/api/grievances/draft", (route) => route.fulfill({ json: citizenDraft }));
  await page.route("**/api/grievances/*/review", async (route) => {
    const updates = route.request().postDataJSON();
    await route.fulfill({ json: { ...citizenDraft, category_id: updates.category_id ?? citizenDraft.category_id, category_label: updates.category_id === "streetlight_out" ? "Streetlight not working" : citizenDraft.category_label, asset_scope: updates.asset_scope ?? citizenDraft.asset_scope, structured_facts: { ...citizenDraft.structured_facts, summary: updates.summary ?? citizenDraft.structured_facts.summary } } });
  });
  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation({ latitude: 18.5204, longitude: 73.8567 });
  await page.goto("/complaints/new");
  await page.getByRole("button", { name: /Use my location/i }).click();
  await page.getByRole("button", { name: /Continue/i }).click();
  await page.getByLabel("Describe the civic issue").fill("Large pothole near the bus stop has damaged two-wheelers.");
  await page.getByRole("button", { name: /Continue/i }).click();
  await page.getByRole("button", { name: /Continue without a photo/i }).click();
  await expect(page.getByRole("heading", { name: "Review what we understood" })).toBeVisible();
}

test("public landing is polished and error free", async ({ page }, testInfo) => {
  const errors = await collectErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open|Start|app/i }).first()).toBeVisible();
  await page.goto("/login");
  await expect(page.getByRole("link", { name: "Official access →" })).toHaveAttribute("href", "/official/login");
  await page.screenshot({ path: testInfo.outputPath("landing.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("citizen complaint review supports correction", async ({ page }, testInfo) => {
  const errors = await collectErrors(page);
  await openReview(page);
  await expect(page.getByText("Pothole or road surface damage")).toBeVisible();
  await expect(page.getByText("Demo Municipal Corporation")).toBeVisible();
  await page.getByRole("button", { name: /Something is wrong/i }).click();
  await page.getByLabel("Issue type").selectOption("streetlight_out");
  await page.getByLabel("Corrected summary").fill("Streetlight outside the bus stop is not working.");
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(page.getByRole("definition").filter({ hasText: "Streetlight not working" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("citizen-review.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("official login and triage action work", async ({ page }, testInfo) => {
  const errors = await collectErrors(page);
  const officialToken = tokenPayload({ sub: "official", aud: "jan-setu-official" });
  const queue = [{ id:"22222222-2222-4222-8222-222222222222", human_id:"JS-20260715-00002", status:"registered", review_status:"pending_official", category_id:"open_or_damaged_manhole", category_label:"Open or damaged manhole", domain:"sewerage_drainage_flooding", department_key:"public_works", priority:"priority", safety_level:"immediate", disposition:"emergency_redirect", confidence:0.88, address:"Nehru Nagar, Pune", issue_text:"Khula manhole school ke saamne hai", structured_facts:{summary:"Open manhole in front of a school",evidence:["khula manhole"]}, routing:{dispatch_enabled:false,owning_agency:"Demo Municipal Corporation"}, flags:["official_review_required"], created_at:new Date().toISOString(), state_version:0 }];
  await page.route("**/api/official/auth/request-code", (route) => route.fulfill({ json: { challenge_id: "33333333-3333-4333-8333-333333333333" } }));
  await page.route("**/api/official/auth/verify", (route) => route.fulfill({ json: { access_token: officialToken, official: { name:"Demo Triage Officer", role:"supervisor", jurisdiction_id:"demo-ulb" } } }));
  await page.route("**/api/official/queue**", (route) => route.fulfill({ json: queue }));
  await page.route("**/api/official/metrics", (route) => route.fulfill({ json: { total_visible:1,pending_review:1,immediate_safety:1,failed_ai:0,failed_dispatch:0 } }));
  await page.route("**/api/official/grievances/*/actions", (route) => route.fulfill({ json: { ...queue[0], review_status:"approved" } }));
  await page.goto("/official/login");
  await page.getByRole("button", { name: "Send one-time code" }).click();
  await page.getByLabel("One-time code").fill("123456");
  await page.getByRole("button", { name: "Open operations console" }).click();
  await expect(page.getByRole("heading", { name: "Civic triage desk" })).toBeVisible();
  await page.getByRole("button", { name: /JS-20260715-00002/ }).click();
  await expect(page.getByText("Immediate safety indicator")).toBeVisible();
  await page.getByLabel("Required decision note").fill("Verified public manhole and immediate school-zone hazard.");
  await page.getByRole("button", { name: "Approve route" }).click();
  await page.screenshot({ path: testInfo.outputPath("official-console.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("all audited pages avoid horizontal overflow", async ({ page }) => {
  await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
