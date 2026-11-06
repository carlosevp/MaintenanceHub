import { describe, expect, it } from "vitest";
import {
  localWallTimeToUtcIso,
  utcIsoToLocalWallTime,
  ZonedDateTimeError,
} from "./zonedDateTime";

describe("zonedDateTime", () => {
  it("interprets datetime-local in America/Chicago not as browser UTC", () => {
    const iso = localWallTimeToUtcIso("2026-01-15T10:30", "America/Chicago");
    // CST = UTC-6 in January
    expect(iso).toBe("2026-01-15T16:30:00.000Z");
  });

  it("handles DST spring-forward gap in America/Chicago", () => {
    // 2026-03-08 02:30 does not exist — should advance or error cleanly
    try {
      const iso = localWallTimeToUtcIso("2026-03-08T02:30", "America/Chicago");
      const wall = utcIsoToLocalWallTime(iso, "America/Chicago");
      expect(wall.startsWith("2026-03-08T0")).toBe(true);
      expect(wall).not.toBe("2026-03-08T02:30");
    } catch (e) {
      expect(e).toBeInstanceOf(ZonedDateTimeError);
    }
  });

  it("round-trips a standard local time", () => {
    const local = "2026-06-01T14:00";
    const iso = localWallTimeToUtcIso(local, "America/New_York");
    expect(utcIsoToLocalWallTime(iso, "America/New_York")).toBe(local);
  });

  it("rejects invalid timezone", () => {
    expect(() => localWallTimeToUtcIso("2026-01-01T00:00", "Not/AZone")).toThrow(
      ZonedDateTimeError,
    );
  });

  it("cross-TZ edit: same UTC wall differs by zone", () => {
    const chicago = localWallTimeToUtcIso("2026-11-01T09:00", "America/Chicago");
    const tokyo = localWallTimeToUtcIso("2026-11-01T09:00", "Asia/Tokyo");
    expect(chicago).not.toBe(tokyo);
  });
});
