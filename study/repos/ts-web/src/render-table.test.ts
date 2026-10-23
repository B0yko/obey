// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { Person, Shift } from "./generated/api-types.js";
import { escapeHtml, renderWeekTable } from "./render-table.js";

const WEEK = new Date("2026-03-02T00:00:00Z");

describe("escapeHtml", () => {
  it("escapes markup characters", () => {
    expect(escapeHtml(`<b onclick="x">Tom & 'Jerry'</b>`)).toBe(
      "&lt;b onclick=&quot;x&quot;&gt;Tom &amp; &#39;Jerry&#39;&lt;/b&gt;",
    );
  });
});

describe("renderWeekTable", () => {
  const people: Person[] = [
    { id: "p1", name: "Ada <Example>", role: "barista" },
    { id: "p2", name: "Bo Example", role: "baker" },
  ];
  const shifts: Shift[] = [
    { id: "s1", personId: "p1", start: "2026-03-04T09:00:00Z", end: "2026-03-04T17:00:00Z", location: "Front & bar" },
  ];

  it("renders one row per person with escaped names, times and total hours", () => {
    const html = renderWeekTable(people, shifts, WEEK);
    expect(html.match(/<tr>/g)).toHaveLength(3);
    expect(html).toContain("Ada &lt;Example&gt;");
    expect(html).toContain("Wed 4 Mar");
    expect(html).toContain('<span class="shift">09:00-17:00 Front &amp; bar</span>');
    expect(html).toContain('<td class="total">8h</td>');
    expect(html).toContain('<td class="total">0h</td>');
  });
});
