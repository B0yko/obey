// SPDX-License-Identifier: Apache-2.0
import { ApiClient } from "./api/client.js";
import { addDays, startOfWeek } from "./date-utils.js";
import { createLogger } from "./logger.js";
import { renderWeekTable } from "./render-table.js";

const logger = createLogger("main");

async function main(): Promise<void> {
  const root = document.querySelector<HTMLElement>("#app");
  if (!root) {
    logger.error("missing #app element");
    return;
  }
  const client = new ApiClient({ baseUrl: root.dataset["apiBase"] ?? "/api" });
  const weekStart = startOfWeek(new Date());
  try {
    const [people, shifts] = await Promise.all([
      client.listPeople(),
      client.listShifts({ from: weekStart, to: addDays(weekStart, 7) }),
    ]);
    root.innerHTML = renderWeekTable(people, shifts, weekStart);
    logger.info("rendered the week", { people: people.length, shifts: shifts.length });
  } catch (error) {
    logger.error("could not load the schedule", error);
    root.textContent = "The schedule could not be loaded. Please try again later.";
  }
}

void main();
