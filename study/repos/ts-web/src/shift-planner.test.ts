// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { NewShift, Person, Shift } from "./generated/api-types.js";
import { findConflicts, groupByDay, validateNewShift, weeklyHours } from "./shift-planner.js";

const WEEK = new Date("2026-03-02T00:00:00Z");

const ada: Person = { id: "p1", name: "Ada Example", role: "barista" };
const bo: Person = { id: "p2", name: "Bo Example", role: "baker", maxWeeklyHours: 10 };

function shift(id: string, personId: string, day: number, startHour: number, endHour: number): Shift {
  const at = (hour: number): string => new Date(Date.UTC(2026, 2, day, hour)).toISOString();
  return { id, personId, start: at(startHour), end: at(endHour) };
}

describe("findConflicts", () => {
  it("reports overlapping shifts for the same person only", () => {
    const shifts = [
      shift("a", "p1", 2, 9, 13),
      shift("b", "p1", 2, 12, 16),
      shift("c", "p2", 2, 12, 16),
      shift("d", "p1", 3, 9, 13),
    ];
    const conflicts = findConflicts(shifts);
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0]?.personId).toBe("p1");
    expect([conflicts[0]?.first.id, conflicts[0]?.second.id]).toEqual(["a", "b"]);
  });
});

describe("weeklyHours and groupByDay", () => {
  const shifts = [shift("a", "p1", 2, 9, 17), shift("b", "p1", 4, 9, 13), shift("c", "p1", 9, 9, 17)];

  it("sums only the shifts that start in the given week", () => {
    expect(weeklyHours(shifts, WEEK).get("p1")).toBe(12);
  });

  it("groups shifts by day and keeps empty days", () => {
    const days = groupByDay(shifts, WEEK);
    expect([...days.keys()]).toHaveLength(7);
    expect(days.get("2026-03-02")?.map((s) => s.id)).toEqual(["a"]);
    expect(days.get("2026-03-03")).toEqual([]);
  });
});

describe("validateNewShift", () => {
  const existing = [shift("a", "p1", 2, 9, 17)];
  const candidate = (personId: string, day: number, startHour: number, endHour: number): NewShift => {
    const { start, end } = shift("new", personId, day, startHour, endHour);
    return { personId, start, end };
  };

  it("accepts a shift that fits", () => {
    expect(validateNewShift(candidate("p1", 3, 9, 17), existing, ada)).toEqual([]);
  });

  it("explains every rule that is broken", () => {
    expect(validateNewShift(candidate("p9", 3, 9, 17), existing, undefined)).toEqual(["unknown person: p9"]);
    expect(validateNewShift(candidate("p1", 3, 17, 9), existing, ada)).toEqual(["a shift must end after it starts"]);
    expect(validateNewShift(candidate("p1", 2, 12, 20), existing, ada)).toEqual(["Ada Example already has a shift then"]);
    expect(validateNewShift(candidate("p2", 3, 6, 20), [], bo)).toEqual([
      "a shift cannot be longer than 12 hours",
      "Bo Example would exceed 10 hours this week",
    ]);
  });
});
