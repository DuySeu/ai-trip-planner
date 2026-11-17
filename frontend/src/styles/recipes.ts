// Tailwind class recipes for the shared pieces of DESIGN.md section 7; colours come from the frontend/index.css tokens

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 text-base whitespace-nowrap no-underline cursor-pointer transition duration-120 ease-standard active:not-disabled:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50";

export const BUTTON = {
  primary: `${BUTTON_BASE} rounded-sm min-h-11 px-5 font-semibold bg-primary text-primary-foreground hover:not-disabled:opacity-90`,
  secondary: `${BUTTON_BASE} rounded-sm min-h-11 px-5 font-semibold bg-secondary text-secondary-foreground hover:not-disabled:bg-accent`,
  destructive: `${BUTTON_BASE} rounded-sm min-h-11 px-5 font-semibold bg-destructive text-destructive-foreground hover:not-disabled:opacity-90`,
  ghost: `${BUTTON_BASE} rounded-sm min-h-9 px-3 font-medium text-foreground hover:not-disabled:bg-accent`,
  icon: `${BUTTON_BASE} rounded-sm size-9 shrink-0 text-foreground hover:not-disabled:bg-accent`,
  iconPrimary: `${BUTTON_BASE} rounded-full size-10 shrink-0 bg-primary text-primary-foreground hover:not-disabled:opacity-90`,
};

export const TITLE = {
  page: "text-title font-bold tracking-tight",
  section: "text-xl font-semibold tracking-tight",
  card: "text-base font-semibold tracking-tight",
};

// SURFACE has no padding, for a card whose content sets its own
export const SURFACE = "rounded-md border border-border bg-card text-card-foreground shadow-surface";
export const CARD = `${SURFACE} p-5`;
export const SKELETON = "rounded-md bg-muted";

const BADGE_BASE = "inline-flex min-h-[22px] items-center gap-1 rounded-full px-2 text-xs font-medium whitespace-nowrap";

export const BADGE = {
  primary: `${BADGE_BASE} bg-primary text-primary-foreground`,
  secondary: `${BADGE_BASE} bg-secondary text-secondary-foreground`,
  accent: `${BADGE_BASE} bg-accent text-accent-foreground`,
  warning: `${BADGE_BASE} bg-warning text-warning-foreground`,
  destructive: `${BADGE_BASE} bg-destructive text-destructive-foreground`,
  muted: `${BADGE_BASE} bg-muted text-muted-foreground`,
};

export const BANNER = {
  warning:
    "flex items-start gap-3 rounded-md border border-warning-foreground/30 bg-warning p-4 text-warning-foreground [&>svg]:shrink-0",
  error: "text-sm text-destructive",
};

export const FIELD = "flex min-w-0 flex-col gap-2";
export const LABEL = "text-sm font-medium";
export const INPUT =
  "w-full min-h-11 rounded-sm border border-input bg-card px-3 disabled:bg-muted aria-invalid:border-destructive";
export const TEXTAREA = `${INPUT} py-3 resize-y`;
export const FIELD_ERROR = "text-sm text-destructive";
export const HELP = "text-sm text-muted-foreground";

export const EMPTY_STATE =
  "flex flex-col items-center gap-4 px-4 py-12 text-center [&>svg]:text-muted-foreground [&_p]:max-w-[48ch]";

export const READING = "mx-auto w-full max-w-(--shell-reading)";
