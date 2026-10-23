// SPDX-License-Identifier: Apache-2.0
// All scheduling maths is done in UTC so results do not depend on the viewer's time zone.

const MS_PER_HOUR = 3_600_000;
const MS_PER_DAY = 24 * MS_PER_HOUR;

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

// A full ISO 8601 date-time with an explicit offset; date-only and zone-less values are rejected.
const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

/** Parse an ISO 8601 date-time that carries a time zone, or throw a RangeError. */
export function parseIsoDateTime(value: string): Date {
  const parsed = new Date(value);
  if (!ISO_DATE_TIME.test(value) || Number.isNaN(parsed.getTime())) {
    throw new RangeError(`invalid ISO date-time: ${value}`);
  }
  return parsed;
}

/** Midnight UTC on the Monday of the week that contains `date`. */
export function startOfWeek(date: Date): Date {
  const daysSinceMonday = (date.getUTCDay() + 6) % 7;
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - daysSinceMonday));
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getTime() + days * MS_PER_DAY);
}

/** The seven days of the week that starts at `weekStart`. */
export function weekDays(weekStart: Date): Date[] {
  return Array.from({ length: 7 }, (_, offset) => addDays(weekStart, offset));
}

/** `YYYY-MM-DD` in UTC, used as a map key for a calendar day. */
export function toDayKey(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function hoursBetween(start: Date, end: Date): number {
  return (end.getTime() - start.getTime()) / MS_PER_HOUR;
}

/** True when the half-open ranges [aStart, aEnd) and [bStart, bEnd) share any time. */
export function rangesOverlap(aStart: Date, aEnd: Date, bStart: Date, bEnd: Date): boolean {
  return aStart < bEnd && bStart < aEnd;
}

/** `HH:MM` in UTC. */
export function formatTime(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}

/** A short column label such as `Mon 3 Mar`. */
export function formatDayLabel(date: Date): string {
  return `${WEEKDAYS[date.getUTCDay()]} ${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}
