// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { ApiClient, ApiError } from "./client.js";

interface RecordedCall {
  url: string;
  init: RequestInit | undefined;
}

function stubFetch(body: unknown, status = 200): { fetchFn: typeof fetch; calls: RecordedCall[] } {
  const calls: RecordedCall[] = [];
  const fetchFn: typeof fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  };
  return { fetchFn, calls };
}

const shiftJson = { id: "s1", personId: "p1", start: "2026-03-04T09:00:00Z", end: "2026-03-04T17:00:00Z" };

describe("ApiClient", () => {
  it("lists people from the items envelope", async () => {
    const { fetchFn, calls } = stubFetch({ items: [{ id: "p1", name: "Ada Example", role: "barista" }] });
    const client = new ApiClient({ baseUrl: "https://team.example.com/api/", fetchFn });
    await expect(client.listPeople()).resolves.toEqual([{ id: "p1", name: "Ada Example", role: "barista" }]);
    expect(calls[0]?.url).toBe("https://team.example.com/api/people");
  });

  it("sends the week range as a query and posts new shifts as JSON", async () => {
    const { fetchFn, calls } = stubFetch(shiftJson);
    const client = new ApiClient({ baseUrl: "/api", fetchFn });
    const from = new Date("2026-03-02T00:00:00Z");
    await client.createShift({ personId: "p1", start: shiftJson.start, end: shiftJson.end });
    expect(calls[0]?.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      personId: "p1",
      start: shiftJson.start,
      end: shiftJson.end,
    });

    const list = stubFetch({ items: [shiftJson] });
    const listing = new ApiClient({ baseUrl: "/api", fetchFn: list.fetchFn });
    await listing.listShifts({ from, to: new Date("2026-03-09T00:00:00Z") });
    expect(list.calls[0]?.url).toBe("/api/shifts?from=2026-03-02T00%3A00%3A00.000Z&to=2026-03-09T00%3A00%3A00.000Z");
  });

  it("raises ApiError for HTTP failures and for bodies of the wrong shape", async () => {
    const failing = new ApiClient({ baseUrl: "/api", fetchFn: stubFetch({ error: "boom" }, 503).fetchFn });
    await expect(failing.listPeople()).rejects.toMatchObject({ name: "ApiError", status: 503 });

    const malformed = new ApiClient({ baseUrl: "/api", fetchFn: stubFetch({ items: [{ id: 7 }] }).fetchFn });
    await expect(malformed.listPeople()).rejects.toBeInstanceOf(ApiError);

    const noEnvelope = new ApiClient({ baseUrl: "/api", fetchFn: stubFetch([]).fetchFn });
    await expect(noEnvelope.listShifts({ from: new Date(0), to: new Date(1) })).rejects.toThrow(/no items array/);
  });
});
