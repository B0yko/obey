// SPDX-License-Identifier: Apache-2.0
// Generated from openapi.yaml by scripts/gen-types.mjs — do not edit.

export const PERSON_ROLE_VALUES = ["barista", "baker", "cashier", "manager"] as const;
export type PersonRole = (typeof PERSON_ROLE_VALUES)[number];

export interface Person {
  id: string;
  name: string;
  role: PersonRole;
  maxWeeklyHours?: number;
}

export interface Shift {
  id: string;
  personId: string;
  start: string;
  end: string;
  location?: string;
}

export interface NewShift {
  personId: string;
  start: string;
  end: string;
  location?: string;
}

export interface PersonList {
  items: Person[];
}

export interface ShiftList {
  items: Shift[];
}
