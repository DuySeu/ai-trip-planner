import type { Language } from "../api/api.types.ts";

const DAY_MS = 86_400_000;
const VIETNAM_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Ho_Chi_Minh",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

// Today in Vietnam as YYYY-MM-DD, whatever zone the browser runs in
export function todayInVietnam(now: Date = new Date()): string {
  return VIETNAM_DATE.format(now);
}

// Shift a YYYY-MM-DD date by whole days
export function addDays(date: string, days: number): string {
  return new Date(Date.parse(date) + days * DAY_MS).toISOString().slice(0, 10);
}

// Days in a trip, counting both ends
export function tripDays(start: string, end: string): number {
  return Math.round((Date.parse(end) - Date.parse(start)) / DAY_MS) + 1;
}

// "Dec 20 - 23, 2026" in the UI language
export function formatDateRange(start: string, end: string, lang: Language): string {
  return new Intl.DateTimeFormat(locale(lang), {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).formatRange(new Date(Date.parse(start)), new Date(Date.parse(end)));
}

// "Sun, Dec 20" in the UI language
export function formatDay(date: string, lang: Language): string {
  return new Intl.DateTimeFormat(locale(lang), {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(Date.parse(date)));
}

// Intl locale for a UI language
export function locale(lang: Language): string {
  return lang === "vi" ? "vi-VN" : "en-US";
}

const VIETNAM_DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Ho_Chi_Minh",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

// "14:05 16/11/2026" for a timestamp, in the Vietnam zone; the same in both UI languages
export function formatDateTime(iso: string): string {
  const parts = Object.fromEntries(VIETNAM_DATE_TIME.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  return `${parts.hour}:${parts.minute} ${parts.day}/${parts.month}/${parts.year}`;
}
