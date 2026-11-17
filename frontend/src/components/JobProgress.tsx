import { Check, TriangleExclamationPoint } from "lucide-react";
import type { TripStatus } from "../api/api.types.ts";
import { type MessageKey, useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON, CARD, TITLE } from "../styles/recipes.ts";

const STEPS = ["queued", "researching", "planning"] as const;
const SECTION = `${CARD} flex flex-col items-start gap-3`;
const STEP: Record<"done" | "current" | "todo", { text: string; dot: string }> = {
  done: { text: "text-foreground", dot: "border-primary bg-primary text-primary-foreground" },
  current: { text: "text-foreground", dot: "border-primary bg-primary animate-breathe" },
  todo: { text: "text-muted-foreground", dot: "border-border" },
};
const KNOWN_FAILURES = ["quota_exhausted", "llm_budget_exceeded", "research_failed", "rate_unavailable"];

interface Props {
  status: TripStatus;
  failureReason: string | null;
  hasPlan: boolean;
  isRetrying: boolean;
  onRetry(): void;
}

// The generation job: three steps while it runs, the reason and a retry once it failed
export function JobProgress({ status, failureReason, hasPlan, isRetrying, onRetry }: Props) {
  const t = useT();

  if (status === "failed") {
    const reason = KNOWN_FAILURES.includes(failureReason ?? "") ? failureReason : "unknown";
    return (
      <section className={SECTION} aria-labelledby="job-title">
        <h2 id="job-title" className={`${TITLE.card} flex items-center gap-2 text-destructive`}>
          <TriangleExclamationPoint size={20} strokeWidth={1.75} aria-hidden="true" />
          {t("trip.failedTitle")}
        </h2>
        <p className="text-destructive" role="alert">
          {t(`trip.failure.${reason}` as MessageKey)}
        </p>
        <button type="button" className={BUTTON.primary} onClick={onRetry} disabled={isRetrying}>
          {t("trip.retry")}
        </button>
      </section>
    );
  }

  const current = STEPS.indexOf(status as (typeof STEPS)[number]);
  return (
    <section className={SECTION} aria-labelledby="job-title" aria-live="polite">
      <h2 id="job-title" className={TITLE.card}>
        {t(hasPlan ? "trip.replanTitle" : "trip.progressTitle")}
      </h2>
      <p className="text-sm text-muted-foreground">{t(hasPlan ? "trip.replanBody" : "trip.progressBody")}</p>
      <ol className="mt-1 flex flex-wrap gap-x-6 gap-y-2">
        {STEPS.map((step, index) => {
          const state = index < current ? "done" : index === current ? "current" : "todo";
          return (
            <li key={step} className={`inline-flex items-center gap-2 text-sm font-medium ${STEP[state].text}`} aria-current={state === "current" ? "step" : undefined}>
              <span className={`inline-grid size-4 place-items-center rounded-full border-2 ${STEP[state].dot}`} aria-hidden="true">
                {state === "done" && <Check size={12} strokeWidth={2.5} />}
              </span>
              {t(`status.${step}`)}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
