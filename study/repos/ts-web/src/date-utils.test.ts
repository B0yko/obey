// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import {
  addDays,
  formatDayLabel,
  formatTime,
  hoursBetween,
  parseIsoDateTime,
  rangesOverlap,
  startOfWeek,
  toDayKey,
} from "./date-utils.js";

describe("parseIsoDateTime", () => {
  it("accepts date-times with an explicit offset", () => {
    expect(parseIsoDateTime("2026-03-04T09:00:00Z").toISOString()).toBe("2026-03-04T09:00:00.000Z");
    expect(parseIsoDateTime("2026-03-04T10:00:00+01:00").toISOString()).toBe("2026-03-04T09:00:00.000Z");
  });

  it("rejects date-only, zone-less and garbage input", () => {
    for (const bad of ["2026-03-04", "2026-03-04T09:00:00", "not a date", "2026-13-40T00:00:00Z"]) {
      expect(() => parseIsoDateTime(bad)).toThrow(RangeError);
    }
  });
});

describe("week helpers", () => {
  it("finds the Monday of the week, including for a Sunday", () => {
    expect(toDayKey(startOfWeek(new Date("2026-03-04T15:30:00Z")))).toBe("2026-03-02");
    expect(toDayKey(startOfWeek(new Date("2026-03-08T23:59:00Z")))).toBe("2026-03-02");
  });

  it("adds days across a month boundary", () => {
    expect(toDayKey(addDays(new Date("2026-02-27T00:00:00Z"), 3))).toBe("2026-03-02");
  });
});

describe("time helpers", () => {
  it("measures hours and formats times in UTC", () => {
    const start = new Date("2026-03-04T09:05:00Z");
    expect(hoursBetween(start, new Date("2026-03-04T17:35:00Z"))).toBe(8.5);
    expect(formatTime(start)).toBe("09:05");
    expect(formatDayLabel(start)).toBe("Wed 4 Mar");
  });

  it("treats touching ranges as not overlapping", () => {
    const at = (hour: number): Date => new Date(Date.UTC(2026, 2, 4, hour));
    expect(rangesOverlap(at(9), at(12), at(12), at(15))).toBe(false);
    expect(rangesOverlap(at(9), at(13), at(12), at(15))).toBe(true);
  });
});
