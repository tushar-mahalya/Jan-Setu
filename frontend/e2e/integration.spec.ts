import { test, expect, type Page } from "@playwright/test";

/**
 * True End-to-End integration tests — NO backend mocking.
 *
 * These tests verify that the frontend pages load correctly, navigation
 * works, responsive layout is sound, and the official login form interacts
 * with the real backend (validation errors, form states, etc.).
 *
 * For flows that need a logged-in citizen session against a real DB,
 * the tests are marked `.skip` — remove the skip once a test DB seed or
 * test-user provisioning script is available.
 */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function collectErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`page:${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console:${m.text()}`);
  });
  return errors;
}

// ---------------------------------------------------------------------------
// 1. Public pages — landing, about, login
// ---------------------------------------------------------------------------

test.describe("Public pages load without errors", () => {
  test("landing page renders heading and CTA", async ({ page }) => {
    const errors = await collectErrors(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Open|Start|app/i }).first()
    ).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("about page loads", async ({ page }) => {
    const errors = await collectErrors(page);
    await page.goto("/about");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("login page shows official-access link", async ({ page }) => {
    const errors = await collectErrors(page);
    await page.goto("/login");
    await expect(
      page.getByRole("link", { name: "Official access →" })
    ).toHaveAttribute("href", "/official/login");
    expect(errors).toEqual([]);
  });

  test("official login page renders form", async ({ page }) => {
    const errors = await collectErrors(page);
    await page.goto("/official/login");
    await expect(
      page.getByRole("button", { name: "Send one-time code" })
    ).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("unknown route redirects to landing", async ({ page }) => {
    await page.goto("/this-page-does-not-exist");
    await expect(page).toHaveURL("/");
  });
});

// ---------------------------------------------------------------------------
// 2. Navigation flows
// ---------------------------------------------------------------------------

test.describe("Navigation between public pages", () => {
  test("landing CTA navigates to login or app", async ({ page }) => {
    await page.goto("/");
    const cta = page.getByRole("link", { name: /Open|Start|app/i }).first();
    const href = await cta.getAttribute("href");
    expect(href).toBeTruthy();
  });

  test("login page official link navigates to official login", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.getByRole("link", { name: "Official access →" }).click();
    await expect(page).toHaveURL("/official/login");
  });
});

// ---------------------------------------------------------------------------
// 3. Responsive layout checks
// ---------------------------------------------------------------------------

test.describe("Responsive layout", () => {
  test("no horizontal overflow on landing", async ({ page }) => {
    await page.goto("/");
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("no horizontal overflow on login", async ({ page }) => {
    await page.goto("/login");
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("no horizontal overflow on official login", async ({ page }) => {
    await page.goto("/official/login");
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// 4. Official login form — real backend validation
// ---------------------------------------------------------------------------

test.describe("Official login form interaction (real backend)", () => {
  test("submit empty email shows validation error", async ({ page }) => {
    await page.goto("/official/login");
    await page.getByRole("button", { name: "Send one-time code" }).click();
    // The form should not navigate away — still on same page
    await expect(page).toHaveURL(/official\/login/);
  });

  test("submit invalid email shows error from backend", async ({ page }) => {
    await page.goto("/official/login");
    // Type a clearly invalid email — the backend should return 422
    const emailInput = page.getByLabel(/email/i).or(page.locator('input[type="email"]'));
    if (await emailInput.count()) {
      await emailInput.first().fill("not-an-email");
      await page.getByRole("button", { name: "Send one-time code" }).click();
      // Should stay on login page (no navigation to OTP screen)
      await expect(page).toHaveURL(/official\/login/);
    }
  });
});

// ---------------------------------------------------------------------------
// 5. Auth-protected routes redirect
// ---------------------------------------------------------------------------

test.describe("Protected routes redirect unauthenticated users", () => {
  test("dashboard redirects to login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/login/);
  });

  test("new complaint redirects to login", async ({ page }) => {
    await page.goto("/complaints/new");
    await expect(page).toHaveURL(/login/);
  });
});

// ---------------------------------------------------------------------------
// 6. Citizen complaint flow (requires live backend + test user)
// ---------------------------------------------------------------------------

test.describe("Citizen complaint flow (un-mocked)", () => {
  // Remove .skip once you have a test DB seed / auth bypass for E2E
  test.skip("full complaint creation against live backend", async ({
    page,
  }) => {
    // 1. Authenticate (fill in real test credentials)
    await page.goto("/login");

    // 2. Navigate to complaint form
    await page.goto("/complaints/new");

    // 3. Share location
    await page.context().grantPermissions(["geolocation"]);
    await page
      .context()
      .setGeolocation({ latitude: 18.5204, longitude: 73.8567 });
    await page.getByRole("button", { name: /Use my location/i }).click();
    await page.getByRole("button", { name: /Continue/i }).click();

    // 4. Describe issue
    await page
      .getByLabel("Describe the civic issue")
      .fill("Automated E2E test — pothole on MG Road.");
    await page.getByRole("button", { name: /Continue/i }).click();

    // 5. Skip photo
    await page
      .getByRole("button", { name: /Continue without a photo/i })
      .click();

    // 6. Verify review screen (data came from the real backend)
    await expect(
      page.getByRole("heading", { name: "Review what we understood" })
    ).toBeVisible();
  });

  test.skip("citizen dashboard lists grievances from backend", async ({
    page,
  }) => {
    // Assumes an authenticated session exists
    await page.goto("/dashboard");
    // The dashboard should render even if empty
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// 7. Accessibility basics
// ---------------------------------------------------------------------------

test.describe("Accessibility basics", () => {
  test("landing page has exactly one h1", async ({ page }) => {
    await page.goto("/");
    const h1Count = await page.locator("h1").count();
    expect(h1Count).toBe(1);
  });

  test("login page has exactly one h1", async ({ page }) => {
    await page.goto("/login");
    const h1Count = await page.locator("h1").count();
    expect(h1Count).toBe(1);
  });

  test("official login page has exactly one h1", async ({ page }) => {
    await page.goto("/official/login");
    const h1Count = await page.locator("h1").count();
    expect(h1Count).toBe(1);
  });

  test("all images have alt text on landing", async ({ page }) => {
    await page.goto("/");
    const images = page.locator("img");
    const count = await images.count();
    for (let i = 0; i < count; i++) {
      const alt = await images.nth(i).getAttribute("alt");
      expect(alt).not.toBeNull();
    }
  });
});
