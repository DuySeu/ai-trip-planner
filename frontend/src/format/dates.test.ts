import { describe, expect, it } from "vitest";
import { addDays, formatDateTime, todayInVietnam, tripDays } from "./dates.ts";

describe("dates", () => {
  it("today_in_vietnam_is_next_day_at_1730_utc", () => {
    expect(todayInVietnam(new Date("2026-11-16T17:30:00Z"))).toBe("2026-11-17");
  });

  it("today_in_vietnam_is_same_day_at_1659_utc", () => {
    expect(todayInVietnam(new Date("2026-11-16T16:59:00Z"))).toBe("2026-11-16");
  });

  it("trip_days_counts_both_ends", () => {
    expect(tripDays("2026-12-20", "2026-12-23")).toBe(4);
  });

  it("add_days_crosses_the_year", () => {
    expect(addDays("2026-12-30", 3)).toBe("2027-01-02");
  });

  it("format_date_time_uses_vietnam_zone_and_24_hour_clock", () => {
    expect(formatDateTime("2026-11-16T17:05:00Z")).toBe("00:05 17/11/2026");
    expect(formatDateTime("2026-01-02T06:30:00Z")).toBe("13:30 02/01/2026");
  });
});
