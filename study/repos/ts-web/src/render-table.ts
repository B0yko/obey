// SPDX-License-Identifier: Apache-2.0
import { formatDayLabel, formatTime, parseIsoDateTime, toDayKey, weekDays } from "./date-utils.js";
import type { Person, Shift } from "./generated/api-types.js";
import { groupByDay, weeklyHours } from "./shift-planner.js";

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** Escape text for use inside HTML element content or a quoted attribute. */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char] ?? char);
}

function renderCell(shifts: readonly Shift[]): string {
  const items = shifts.map((shift) => {
    const range = `${formatTime(parseIsoDateTime(shift.start))}-${formatTime(parseIsoDateTime(shift.end))}`;
    const place = shift.location ? ` ${escapeHtml(shift.location)}` : "";
    return `<span class="shift">${range}${place}</span>`;
  });
  return `<td>${items.join("<br>")}</td>`;
}

/** Render the weekly rota as an HTML table: one row per person, one column per day. */
export function renderWeekTable(people: readonly Person[], shifts: readonly Shift[], weekStart: Date): string {
  const days = weekDays(weekStart);
  const hours = weeklyHours(shifts, weekStart);
  const header = days.map((day) => `<th scope="col">${escapeHtml(formatDayLabel(day))}</th>`).join("");
  const rows = people.map((person) => {
    const own = groupByDay(
      shifts.filter((shift) => shift.personId === person.id),
      weekStart,
    );
    const cells = days.map((day) => renderCell(own.get(toDayKey(day)) ?? [])).join("");
    const total = hours.get(person.id) ?? 0;
    return `<tr><th scope="row">${escapeHtml(person.name)}</th>${cells}<td class="total">${total}h</td></tr>`;
  });
  return [
    '<table class="week">',
    `<thead><tr><th scope="col">Team</th>${header}<th scope="col">Hours</th></tr></thead>`,
    `<tbody>${rows.join("")}</tbody>`,
    "</table>",
  ].join("");
}
