// SPDX-License-Identifier: Apache-2.0
import type { NewShift, Person, Shift } from "../generated/api-types.js";
import { isPerson, isRecord, isShift } from "./response-guards.js";

export class ApiError extends Error {
  readonly status: number | undefined;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  fetchFn?: typeof fetch;
}

export interface DateRange {
  from: Date;
  to: Date;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchFn: typeof fetch;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.fetchFn = options.fetchFn ?? globalThis.fetch.bind(globalThis);
  }

  async listPeople(): Promise<Person[]> {
    return parseItems(await this.request("/people"), isPerson, "people");
  }

  async listShifts(range: DateRange): Promise<Shift[]> {
    const query = new URLSearchParams({ from: range.from.toISOString(), to: range.to.toISOString() });
    return parseItems(await this.request(`/shifts?${query.toString()}`), isShift, "shifts");
  }

  async createShift(input: NewShift): Promise<Shift> {
    const body = await this.request("/shifts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!isShift(body)) throw new ApiError("the server returned an unexpected shape for the new shift");
    return body;
  }

  private async request(path: string, init?: RequestInit): Promise<unknown> {
    const response = await this.fetchFn(`${this.baseUrl}${path}`, init);
    if (!response.ok) {
      throw new ApiError(`request to ${path} failed with status ${response.status}`, response.status);
    }
    const body: unknown = await response.json();
    return body;
  }
}

function parseItems<T>(body: unknown, guard: (value: unknown) => value is T, what: string): T[] {
  if (!isRecord(body) || !Array.isArray(body["items"])) {
    throw new ApiError(`the ${what} response has no items array`);
  }
  const items: unknown[] = body["items"];
  const badIndex = items.findIndex((item) => !guard(item));
  if (badIndex !== -1) throw new ApiError(`${what}[${badIndex}] has an unexpected shape`);
  return items.filter(guard);
}
