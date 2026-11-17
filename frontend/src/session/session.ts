import { useSyncExternalStore } from "react";

const STORAGE_KEY = "tripPlanner.session";
const CHANGE_EVENT = "tripPlanner.session-change";

export interface Session {
  userId: string;
  name: string;
}

let lastRaw: string | null = null;
let lastSession: Session | null = null;

// The stored session; the same object comes back until storage changes (useSyncExternalStore needs that)
export function readSession(): Session | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (raw !== lastRaw) {
    lastRaw = raw;
    lastSession = parse(raw);
  }
  return lastSession;
}

// Store the session and tell this tab
export function saveSession(session: Session): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Storage blocked: the name lasts for this page only
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

// Forget the session ("Switch name")
export function clearSession(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage blocked: nothing was stored
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

// The current session, in sync across this tab and other tabs
export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, readSession, () => null);
}

// Listen to this tab's own changes and to other tabs' storage events
function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

// Stored JSON as a session; anything malformed counts as no session
function parse(raw: string | null): Session | null {
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return null;
    const { userId, name } = value as Record<string, unknown>;
    return typeof userId === "string" && typeof name === "string" ? { userId, name } : null;
  } catch {
    return null;
  }
}
