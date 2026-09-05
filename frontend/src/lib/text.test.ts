import { describe, expect, it } from "vitest";
import { humanizeKey } from "./text";

describe("humanizeKey", () => {
  it("converts snake_case to a capitalized phrase", () => {
    expect(humanizeKey("insufficient_information")).toBe("Insufficient information");
  });

  it("returns null for null or undefined input", () => {
    expect(humanizeKey(null)).toBeNull();
    expect(humanizeKey(undefined)).toBeNull();
  });

  it("returns null for an empty/whitespace-only string", () => {
    expect(humanizeKey("   ")).toBeNull();
  });
});
