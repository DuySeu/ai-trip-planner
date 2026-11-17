import { describe, expect, it } from "vitest";
import { formatMoney, toVnd } from "./money.ts";

// Intl uses no-break spaces in some locales; compare with plain spaces
function plain(text: string): string {
  return text.replace(/[\u00a0\u202f]/g, " ");
}

describe("money", () => {
  it("format_money_vnd_in_vi_has_dot_groups_and_no_decimals", () => {
    expect(plain(formatMoney("1250000.00", "VND", "vi"))).toBe("1.250.000 ₫");
  });

  it("format_money_thb_in_en_keeps_two_decimals", () => {
    expect(plain(formatMoney("350", "THB", "en"))).toBe("THB 350.00");
  });

  it("to_vnd_rounds_to_nearest_thousand", () => {
    expect(toVnd("350", 720.5)).toBe(252000);
  });
});
