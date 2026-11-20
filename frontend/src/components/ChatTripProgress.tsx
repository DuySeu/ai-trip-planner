import { Link } from "react-router";
import { ApiError } from "../api/client.ts";
import { useRetryTrip, useTrip } from "../api/trips.ts";
import { formatMoney } from "../format/money.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { BADGE, BANNER, BUTTON, CARD, SKELETON, TITLE } from "../styles/recipes.ts";
import { JobProgress } from "./JobProgress.tsx";
import { TripFacts } from "./TripFacts.tsx";

// What became of a trip made from a chat form: progress while it runs, a link when ready, the reason when it failed
export function ChatTripProgress({ tripId }: { tripId: string }) {
  const t = useT();
  const { lang } = useLanguage();
  const trip = useTrip(tripId);
  const retry = useRetryTrip();

  if (trip.isPending) return <div className={`${SKELETON} h-24 w-full`} aria-label={t("home.loading")} />;

  if (trip.isError) {
    const isMissing = trip.error instanceof ApiError && trip.error.status === 404;
    return <p className={isMissing ? "text-sm text-muted-foreground" : BANNER.error}>{isMissing ? t("chat.tripForm.deleted") : t(errorKey(trip.error))}</p>;
  }

  const data = trip.data;
  if (data.status === "ready") {
    return (
      <section className={`${CARD} flex w-full flex-col gap-3`}>
        <h3 className={TITLE.card}>{data.destination.name}</h3>
        <TripFacts
          origin={data.origin}
          destination={data.destination.name}
          startDate={data.start_date}
          endDate={data.end_date}
          travelers={data.travelers}
          styles={data.travel_styles}
          budgetAmount={data.budget_amount}
          budgetScope={data.budget_scope}
        />
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <span className={BADGE.accent}>{t("status.ready")}</span>
          {data.over_budget && <span className={BADGE.warning}>{t("badge.overBudget")}</span>}
          {data.total_cost_vnd !== null && (
            <span className="text-sm font-medium tabular-nums">{t("home.total", { amount: formatMoney(data.total_cost_vnd, "VND", lang) })}</span>
          )}
          <Link to={`/trips/${data.id}`} className={`${BUTTON.primary} ml-auto`}>
            {t("chat.tripForm.openTrip")}
          </Link>
        </div>
      </section>
    );
  }

  return (
    <div className="flex w-full flex-col gap-2">
      <JobProgress
        status={data.status}
        failureReason={data.failure_reason}
        hasPlan={data.plan !== null}
        isRetrying={retry.isPending}
        onRetry={() => retry.mutate(data.id)}
      />
      {retry.isError && (
        <p className={BANNER.error} role="alert">
          {t(errorKey(retry.error))}
        </p>
      )}
    </div>
  );
}
