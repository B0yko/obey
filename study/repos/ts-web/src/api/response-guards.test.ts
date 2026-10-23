// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { isPerson, isPersonRole, isRecord, isShift } from "./response-guards.js";

describe("response guards", () => {
  it("accept well-formed values and reject everything else", () => {
    expect(isRecord({})).toBe(true);
    expect(isRecord([])).toBe(false);
    expect(isRecord(null)).toBe(false);

    expect(isPersonRole("baker")).toBe(true);
    expect(isPersonRole("pilot")).toBe(false);

    expect(isPerson({ id: "p1", name: "Ada", role: "barista", maxWeeklyHours: 20 })).toBe(true);
    expect(isPerson({ id: "p1", name: "Ada", role: "pilot" })).toBe(false);
    expect(isPerson({ id: "p1", name: "Ada", role: "barista", maxWeeklyHours: "20" })).toBe(false);

    expect(isShift({ id: "s", personId: "p", start: "a", end: "b", location: "Bar" })).toBe(true);
    expect(isShift({ id: "s", personId: "p", start: "a" })).toBe(false);
  });
});
