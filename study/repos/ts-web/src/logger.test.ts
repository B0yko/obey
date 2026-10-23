// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { createLogger } from "./logger.js";
import type { LogSink } from "./logger.js";

describe("createLogger", () => {
  it("prefixes messages with the scope and drops levels below the minimum", () => {
    const seen: string[] = [];
    const record =
      (level: string) =>
      (...args: unknown[]): void => {
        seen.push(`${level}:${String(args[0])}`);
      };
    const sink: LogSink = { debug: record("debug"), info: record("info"), warn: record("warn"), error: record("error") };

    const logger = createLogger("planner", { level: "warn", sink });
    logger.debug("hidden");
    logger.info("hidden too");
    logger.warn("two shifts overlap");
    logger.error("failed");

    expect(seen).toEqual(["warn:[planner] two shifts overlap", "error:[planner] failed"]);
  });
});
