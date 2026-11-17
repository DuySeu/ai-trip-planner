import { CalendarDays, Luggage, Plus, Trash, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { TripStatus, TripSummary } from "../api/api.types.ts";
import { useDeleteTrip, useUserTrips } from "../api/trips.ts";
import { ConfirmDialog } from "../components/ConfirmDialog.tsx";
import { EmptyState } from "../components/EmptyState.tsx";
import { formatDateRange } from "../format/dates.ts";
import { formatMoney } from "../format/money.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { useSession } from "../session/session.ts";
import { BADGE, BUTTON, CARD, SKELETON, TITLE } from "../styles/recipes.ts";

const SKELETON_CARDS = ["a", "b", "c"];
const STATUS_BADGE: Record<TripStatus, string> = {
  queued: BADGE.secondary,
  researching: BADGE.secondary,
  planning: BADGE.secondary,
  ready: BADGE.accent,
  failed: BADGE.destructive,
};
const GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3";
const META = "flex items-center gap-2 text-sm text-muted-foreground";

// The visitor's trips as cards; chats live in the sidebar
export function HomePage() {
  const t = useT();
  const { lang } = useLanguage();
  const session = useSession();
  const userId = session?.userId ?? "";
  const [pendingDelete, setPendingDelete] = useState<TripSummary | null>(null);
  const trips = useUserTrips(userId);
  const deleteTrip = useDeleteTrip();

  // Delete after the visitor confirms
  const handleConfirmDelete = () => {
    if (!pendingDelete) return;
    deleteTrip.mutate(pendingDelete.id, { onSuccess: () => setPendingDelete(null) });
  };

  const newTripLink = (
    <Link to="/trips/new" className={BUTTON.primary}>
      <Plus size={20} strokeWidth={1.75} aria-hidden="true" />
      {t("home.newTrip")}
    </Link>
  );

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className={TITLE.page}>{t("home.title")}</h1>
        {trips.data && trips.data.length > 0 && newTripLink}
      </header>

      {trips.isPending ? (
        <ul className={GRID} aria-label={t("home.loading")}>
          {SKELETON_CARDS.map((key) => (
            <li key={key} className={`${SKELETON} h-[172px]`} />
          ))}
        </ul>
      ) : trips.isError ? (
        <div className="flex flex-wrap items-center gap-4 text-destructive" role="alert">
          <p>{t(errorKey(trips.error))}</p>
          <button type="button" className={BUTTON.secondary} onClick={() => trips.refetch()}>
            {t("common.retry")}
          </button>
        </div>
      ) : trips.data.length === 0 ? (
        <EmptyState icon={Luggage} text={t("home.empty")} action={newTripLink} />
      ) : (
        <ul className={GRID}>
          {trips.data.map((trip) => (
            <li key={trip.id} className={`${CARD} relative flex flex-col gap-2 transition duration-120 ease-standard hover:border-input active:scale-[0.99]`}>
              <div className="flex items-start justify-between gap-2">
                <h2 className={TITLE.section}>
                  <Link to={`/trips/${trip.id}`} className="text-card-foreground no-underline wrap-anywhere after:absolute after:inset-0 after:rounded-md focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-offset-2 focus-visible:after:outline-ring">
                    {trip.destination_name}
                  </Link>
                </h2>
                <button
                  type="button"
                  className={`${BUTTON.icon} relative z-[1] -mt-2 -mr-2 text-muted-foreground hover:text-destructive`}
                  aria-label={t("home.deleteTrip", { destination: trip.destination_name })}
                  onClick={() => setPendingDelete(trip)}
                >
                  <Trash size={20} strokeWidth={1.75} />
                </button>
              </div>
              <p className={`${META} tabular-nums`}>
                <CalendarDays size={16} strokeWidth={1.75} aria-hidden="true" />
                {formatDateRange(trip.start_date, trip.end_date, lang)}
              </p>
              <p className={META}>
                <Users size={16} strokeWidth={1.75} aria-hidden="true" />
                {t("common.travelers", { count: trip.travelers })}
              </p>
              <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-border pt-3">
                <span className={STATUS_BADGE[trip.status]}>{t(`status.${trip.status}`)}</span>
                {trip.over_budget && <span className={BADGE.warning}>{t("badge.overBudget")}</span>}
                {trip.total_cost_vnd !== null && (
                  <span className="ml-auto text-sm font-medium tabular-nums">
                    {t("home.total", { amount: formatMoney(trip.total_cost_vnd, "VND", lang) })}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        isOpen={pendingDelete !== null}
        title={t("home.deleteTitle", { destination: pendingDelete?.destination_name ?? "" })}
        body={deleteTrip.isError ? t(errorKey(deleteTrip.error)) : t("home.deleteBody")}
        confirmLabel={t("home.deleteConfirm")}
        isBusy={deleteTrip.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => {
          deleteTrip.reset();
          setPendingDelete(null);
        }}
      />
    </div>
  );
}
