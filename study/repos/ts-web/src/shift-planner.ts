// SPDX-License-Identifier: Apache-2.0
import {
  addDays,
  hoursBetween,
  parseIsoDateTime,
  rangesOverlap,
  startOfWeek,
  toDayKey,
  weekDays,
} from "./date-utils.js";
import type { NewShift, Person, Shift } from "./generated/api-types.js";

export const MAX_SHIFT_HOURS = 12;
export const DEFAULT_WEEKLY_LIMIT = 40;

export interface Conflict {
  personId: string;
  first: Shift;
  second: Shift;
}

function byStart(a: Shift, b: Shift): number {
  return parseIsoDateTime(a.start).getTime() - parseIsoDateTime(b.start).getTime();
}

/** Pairs of shifts that overlap for the same person. */
export function findConflicts(shifts: readonly Shift[]): Conflict[] {
  const byPerson = new Map<string, Shift[]>();
  for (const shift of shifts) {
    byPerson.set(shift.personId, [...(byPerson.get(shift.personId) ?? []), shift]);
  }
  const conflicts: Conflict[] = [];
  for (const [personId, list] of byPerson) {
    const sorted = [...list].sort(byStart);
    for (let i = 0; i < sorted.length; i += 1) {
      for (let j = i + 1; j < sorted.length; j += 1) {
        const first = sorted[i];
        const second = sorted[j];
        if (first && second && overlaps(first, second)) conflicts.push({ personId, first, second });
      }
    }
  }
  return conflicts;
}

function overlaps(a: Pick<Shift, "start" | "end">, b: Pick<Shift, "start" | "end">): boolean {
  return rangesOverlap(
    parseIsoDateTime(a.start),
    parseIsoDateTime(a.end),
    parseIsoDateTime(b.start),
    parseIsoDateTime(b.end),
  );
}

/** Scheduled hours per person id for shifts that start in the week beginning at `weekStart`. */
export function weeklyHours(shifts: readonly Shift[], weekStart: Date): Map<string, number> {
  const weekEnd = addDays(weekStart, 7);
  const totals = new Map<string, number>();
  for (const shift of shifts) {
    const start = parseIsoDateTime(shift.start);
    if (start < weekStart || start >= weekEnd) continue;
    const hours = hoursBetween(start, parseIsoDateTime(shift.end));
    totals.set(shift.personId, (totals.get(shift.personId) ?? 0) + hours);
  }
  return totals;
}

/** Shifts grouped by the UTC day they start on, one (possibly empty) entry for each day of the week. */
export function groupByDay(shifts: readonly Shift[], weekStart: Date): Map<string, Shift[]> {
  const days = new Map<string, Shift[]>(
    weekDays(weekStart).map((day): [string, Shift[]] => [toDayKey(day), []]),
  );
  for (const shift of [...shifts].sort(byStart)) {
    days.get(toDayKey(parseIsoDateTime(shift.start)))?.push(shift);
  }
  return days;
}

/** Reasons a new shift cannot be added; an empty list means it is fine. */
export function validateNewShift(
  candidate: NewShift,
  existing: readonly Shift[],
  person: Person | undefined,
): string[] {
  if (!person) return [`unknown person: ${candidate.personId}`];
  const start = parseIsoDateTime(candidate.start);
  const end = parseIsoDateTime(candidate.end);
  if (end <= start) return ["a shift must end after it starts"];

  const errors: string[] = [];
  const length = hoursBetween(start, end);
  if (length > MAX_SHIFT_HOURS) errors.push(`a shift cannot be longer than ${MAX_SHIFT_HOURS} hours`);

  const own = existing.filter((shift) => shift.personId === person.id);
  if (own.some((shift) => overlaps(candidate, shift))) errors.push(`${person.name} already has a shift then`);

  const planned = weeklyHours(own, startOfWeek(start)).get(person.id) ?? 0;
  const limit = person.maxWeeklyHours ?? DEFAULT_WEEKLY_LIMIT;
  if (planned + length > limit) errors.push(`${person.name} would exceed ${limit} hours this week`);
  return errors;
}
