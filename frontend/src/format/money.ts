import type { Language } from "../api/api.types.ts";
import { locale } from "./dates.ts";

const VND_STEP = 1000;

// Local currency per destination country; a country missing here cannot be planned
export const COUNTRY_CURRENCY: Readonly<Record<string, string>> = {
  VN: "VND",
  TH: "THB",
  SG: "SGD",
  JP: "JPY",
  KR: "KRW",
  FR: "EUR",
};

// An amount in its own currency, formatted for the UI language
export function formatMoney(amount: string | number, currency: string, lang: Language): string {
  return new Intl.NumberFormat(locale(lang), {
    style: "currency",
    currency,
    maximumFractionDigits: currency === "VND" ? 0 : 2,
  }).format(Number(amount));
}

// A local-currency price in VND for display only, rounded to the nearest 1000
export function toVnd(amount: string, rate: number): number {
  return Math.round((Number(amount) * rate) / VND_STEP) * VND_STEP;
}
