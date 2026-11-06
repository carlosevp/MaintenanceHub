/**
 * Interpret datetime-local wall times in a selected IANA timezone (not the browser zone).
 *
 * Handles DST gaps (nonexistent local times) by advancing to the next valid instant,
 * and ambiguous times (fall-back overlap) by preferring the earlier offset (DST).
 */

export class ZonedDateTimeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ZonedDateTimeError";
  }
}

const LOCAL_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

function assertValidTimeZone(timeZone: string): void {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone }).format(new Date());
  } catch {
    throw new ZonedDateTimeError(`Invalid IANA timezone: ${timeZone}`);
  }
}

function partsInZone(date: Date, timeZone: string) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const map: Record<string, string> = {};
  for (const p of fmt.formatToParts(date)) {
    if (p.type !== "literal") map[p.type] = p.value;
  }
  return {
    year: Number(map.year),
    month: Number(map.month),
    day: Number(map.day),
    hour: Number(map.hour),
    minute: Number(map.minute),
    second: Number(map.second ?? "0"),
  };
}

function asUtcGuess(y: number, m: number, d: number, hh: number, mm: number, ss: number): Date {
  return new Date(Date.UTC(y, m - 1, d, hh, mm, ss));
}

/**
 * Convert a datetime-local value (`YYYY-MM-DDTHH:mm`) interpreted in `timeZone` to UTC ISO.
 */
export function localWallTimeToUtcIso(local: string, timeZone: string): string {
  assertValidTimeZone(timeZone);
  const m = LOCAL_RE.exec(local.trim());
  if (!m) {
    throw new ZonedDateTimeError(`Invalid datetime-local value: ${local}`);
  }
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  const second = Number(m[6] ?? "0");

  // Initial guess: treat wall components as UTC, then correct by zone offset.
  let utc = asUtcGuess(year, month, day, hour, minute, second);
  for (let i = 0; i < 3; i++) {
    const parts = partsInZone(utc, timeZone);
    const asWanted = asUtcGuess(year, month, day, hour, minute, second);
    const asGot = asUtcGuess(parts.year, parts.month, parts.day, parts.hour, parts.minute, parts.second);
    const delta = asWanted.getTime() - asGot.getTime();
    if (delta === 0) break;
    utc = new Date(utc.getTime() + delta);
  }

  const verify = partsInZone(utc, timeZone);
  const matches =
    verify.year === year &&
    verify.month === month &&
    verify.day === day &&
    verify.hour === hour &&
    verify.minute === minute;

  if (!matches) {
    // Nonexistent local time (spring-forward gap): nudge forward up to 2h to next valid wall time.
    let nudged = asUtcGuess(year, month, day, hour, minute, second);
    let found: Date | null = null;
    for (let step = 0; step < 120; step++) {
      nudged = new Date(nudged.getTime() + 60_000);
      const p = partsInZone(nudged, timeZone);
      // After gap, clock lands on a later wall time same calendar day or next.
      if (p.year === year && p.month === month && p.day === day && p.hour >= hour) {
        // Re-resolve that wall time precisely
        found = resolveExact(year, month, day, p.hour, p.minute, 0, timeZone);
        break;
      }
    }
    if (!found) {
      throw new ZonedDateTimeError(
        `Local time ${local} does not exist in ${timeZone} (DST gap)`,
      );
    }
    utc = found;
  }

  return utc.toISOString();
}

function resolveExact(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  second: number,
  timeZone: string,
): Date {
  let utc = asUtcGuess(year, month, day, hour, minute, second);
  for (let i = 0; i < 3; i++) {
    const parts = partsInZone(utc, timeZone);
    const asWanted = asUtcGuess(year, month, day, hour, minute, second);
    const asGot = asUtcGuess(parts.year, parts.month, parts.day, parts.hour, parts.minute, parts.second);
    const delta = asWanted.getTime() - asGot.getTime();
    if (delta === 0) break;
    utc = new Date(utc.getTime() + delta);
  }
  return utc;
}

/**
 * Format a UTC ISO string as datetime-local wall time in `timeZone`.
 */
export function utcIsoToLocalWallTime(iso: string, timeZone: string): string {
  assertValidTimeZone(timeZone);
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    throw new ZonedDateTimeError(`Invalid ISO timestamp: ${iso}`);
  }
  const p = partsInZone(date, timeZone);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
}

export function seedsKey(seeds: Array<{ target_type: string; target_id: string; environment_id?: string | null }>): string {
  return seeds
    .map((s) => `${s.target_type}:${s.target_id}:${s.environment_id ?? ""}`)
    .sort()
    .join("|");
}
