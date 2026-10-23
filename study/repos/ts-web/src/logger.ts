// SPDX-License-Identifier: Apache-2.0
export type LogLevel = "debug" | "info" | "warn" | "error";

export interface LogSink {
  debug(...args: unknown[]): void;
  info(...args: unknown[]): void;
  warn(...args: unknown[]): void;
  error(...args: unknown[]): void;
}

export interface Logger {
  debug(message: string, ...context: unknown[]): void;
  info(message: string, ...context: unknown[]): void;
  warn(message: string, ...context: unknown[]): void;
  error(message: string, ...context: unknown[]): void;
}

export interface LoggerOptions {
  level?: LogLevel;
  sink?: LogSink;
}

const LEVEL_ORDER: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

/** Create a scoped logger; this is the only place in the app that talks to the console. */
export function createLogger(scope: string, options: LoggerOptions = {}): Logger {
  const minimum = LEVEL_ORDER[options.level ?? "info"];
  const sink = options.sink ?? console;
  const emit =
    (level: LogLevel) =>
    (message: string, ...context: unknown[]): void => {
      if (LEVEL_ORDER[level] < minimum) return;
      sink[level](`[${scope}] ${message}`, ...context);
    };
  return { debug: emit("debug"), info: emit("info"), warn: emit("warn"), error: emit("error") };
}
