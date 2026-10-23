// SPDX-License-Identifier: Apache-2.0
// The team API is not under our control and returns plain JSON, so every response is checked
// by hand before it is treated as one of the generated types.
import { PERSON_ROLE_VALUES } from "../generated/api-types.js";
import type { Person, PersonRole, Shift } from "../generated/api-types.js";

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isOptional(value: unknown, type: "string" | "number"): boolean {
  return value === undefined || typeof value === type;
}

export function isPersonRole(value: unknown): value is PersonRole {
  return PERSON_ROLE_VALUES.some((role) => role === value);
}

export function isPerson(value: unknown): value is Person {
  return (
    isRecord(value) &&
    typeof value["id"] === "string" &&
    typeof value["name"] === "string" &&
    isPersonRole(value["role"]) &&
    isOptional(value["maxWeeklyHours"], "number")
  );
}

export function isShift(value: unknown): value is Shift {
  return (
    isRecord(value) &&
    typeof value["id"] === "string" &&
    typeof value["personId"] === "string" &&
    typeof value["start"] === "string" &&
    typeof value["end"] === "string" &&
    isOptional(value["location"], "string")
  );
}
