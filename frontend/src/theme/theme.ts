const STORAGE_KEY = "tripPlanner.theme";

export type Theme = "light" | "dark";

// The stored choice, else the system preference, else light
export function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Storage blocked: fall back to the system preference
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Show a theme without storing it (startup)
export function showTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

// Switch the theme and remember the explicit choice
export function applyTheme(theme: Theme): void {
  showTheme(theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Storage blocked: the choice lasts for this page only
  }
}
