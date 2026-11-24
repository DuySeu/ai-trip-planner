import { useState } from "react";
import { useSearchParams } from "react-router";
import type { HealthStats, StatCount, UsageDays, UsageStats } from "../api/api.types.ts";
import { useHealthStats, useUsageStats } from "../api/stats.ts";
import { BarList } from "../components/BarList.tsx";
import { DailyChart } from "../components/DailyChart.tsx";
import { StatTile } from "../components/StatTile.tsx";
import { formatDateTime, formatDay, locale } from "../format/dates.ts";
import { formatMoney } from "../format/money.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { type MessageKey, type Translate, useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON, CARD, SKELETON, TITLE } from "../styles/recipes.ts";
import { blockTone, errorTone, llmTone, queueTone } from "./dashboardTone.ts";

const RANGES: UsageDays[] = [7, 30, 90];
const DEFAULT_RANGE: UsageDays = 30;
const NONE = "-";
const MS_PER_S = 1000;
const S_PER_MIN = 60;
const GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4";
const LIST_GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3";
const INTENT_KEY: Record<string, MessageKey> = {
  advice: "dashboard.intent.advice",
  discover: "dashboard.intent.discover",
  booking_search: "dashboard.intent.booking_search",
  create_trip: "dashboard.intent.create_trip",
  edit_plan: "dashboard.intent.edit_plan",
};
const FORM_KEY: Record<string, MessageKey> = {
  open: "dashboard.form.open",
  created: "dashboard.form.created",
  canceled: "dashboard.form.canceled",
};
const STYLE_KEY: Record<string, MessageKey> = {
  relax: "style.relax",
  adventure: "style.adventure",
  culture: "style.culture",
  food: "style.food",
  nature: "style.nature",
  nightlife: "style.nightlife",
  shopping: "style.shopping",
  luxury: "style.luxury",
  budget: "style.budget",
};

// System health (refreshed every 30 seconds) above usage over 7, 30 or 90 days
export function DashboardPage() {
  const t = useT();
  const [searchParams, setSearchParams] = useSearchParams();
  const days = RANGES.find((d) => String(d) === searchParams.get("days")) ?? DEFAULT_RANGE;

  return (
    <div className="flex flex-col gap-8">
      <h1 className={TITLE.page}>{t("dashboard.title")}</h1>
      <HealthSection />
      <section aria-labelledby="dashboard-usage" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="dashboard-usage" className={TITLE.section}>
            {t("dashboard.usage")}
          </h2>
          <div className="flex gap-1" role="group" aria-label={t("dashboard.range")}>
            {RANGES.map((range) => (
              <button
                key={range}
                type="button"
                aria-pressed={range === days}
                className={`${BUTTON.ghost} ${range === days ? "bg-accent text-accent-foreground" : ""}`}
                onClick={() => setSearchParams({ days: String(range) })}
              >
                {t("dashboard.days", { count: range })}
              </button>
            ))}
          </div>
        </div>
        <UsageSection days={days} />
        <p className="text-sm text-muted-foreground">{t("dashboard.dataNote")}</p>
      </section>
    </div>
  );
}

// The health tiles, or a retry when the first load failed; a failed refresh keeps the last numbers
function HealthSection() {
  const t = useT();
  const { lang } = useLanguage();
  const health = useHealthStats();
  const n = numberFormat(lang);

  return (
    <section aria-labelledby="dashboard-health" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="dashboard-health" className={TITLE.section}>
          {t("dashboard.health")}
        </h2>
        {health.data && (
          <p className={`text-sm ${health.isRefetchError ? "text-destructive" : "text-muted-foreground"}`}>
            {t(health.isRefetchError ? "dashboard.stale" : "dashboard.updated", { time: formatDateTime(health.data.generated_at) })}
          </p>
        )}
      </div>
      {health.isPending ? (
        <div className={GRID} aria-label={t("home.loading")}>
          {RANGES.map((key) => (
            <div key={key} className={`${SKELETON} h-28`} />
          ))}
        </div>
      ) : health.isError && !health.data ? (
        <Failure message={t(errorKey(health.error))} onRetry={() => health.refetch()} />
      ) : (
        <HealthTiles data={health.data} t={t} n={n} />
      )}
    </section>
  );
}

// Eight tiles: LLM use, queue, errors, blocks, then latency, plan time, failures, tokens
function HealthTiles({ data, t, n }: { data: HealthStats; t: Translate; n: Intl.NumberFormat }) {
  const { llm_today: today, llm_last_hour: hour, jobs, plans_last_day: plans } = data;
  const topError = hour.outcomes.find((o) => o.key !== "ok");
  const lastFailure = plans.last_failure;

  return (
    <div className={GRID}>
      <StatTile
        label={t("dashboard.llmToday")}
        value={n.format(today.calls)}
        detail={t("dashboard.llmCeilings", { trips: n.format(today.ceiling_new_trips), chat: n.format(today.ceiling_chat) })}
        tone={llmTone(today.calls, today.ceiling_new_trips)}
      />
      <StatTile
        label={t("dashboard.jobQueue")}
        value={t("dashboard.queueValue", { queued: n.format(jobs.queued), running: n.format(jobs.running) })}
        detail={jobs.oldest_queued_s === null ? t("dashboard.queueEmpty") : t("dashboard.oldestWait", { wait: duration(jobs.oldest_queued_s, n) })}
        tone={queueTone(jobs.oldest_queued_s)}
      />
      <StatTile
        label={t("dashboard.llmErrors")}
        value={hour.calls === 0 ? NONE : percent(hour.errors, hour.calls, n)}
        detail={t("dashboard.callsLastHour", { calls: n.format(hour.calls) }) + (topError ? ` · ${topError.key}` : "")}
        tone={errorTone(hour.errors, hour.calls)}
      />
      <StatTile
        label={t("dashboard.blocks")}
        value={data.blocks.length === 0 ? t("dashboard.noBlocks") : data.blocks.map((b) => b.service).join(", ")}
        detail={data.blocks[0] ? t("dashboard.blockedUntil", { time: formatDateTime(data.blocks[0].blocked_until) }) : undefined}
        tone={blockTone(data.blocks.length)}
      />
      <StatTile label={t("dashboard.latency")} value={`${seconds(hour.p50_latency_ms, MS_PER_S, n)} / ${seconds(hour.p95_latency_ms, MS_PER_S, n)}`} detail={t("dashboard.p50p95")} />
      <StatTile label={t("dashboard.planTime")} value={`${seconds(plans.p50_s, 1, n)} / ${seconds(plans.p95_s, 1, n)}`} detail={t("dashboard.planTimeDetail", { count: n.format(plans.succeeded) })} />
      <StatTile
        label={t("dashboard.failedJobs")}
        value={n.format(plans.failed)}
        detail={lastFailure ? t("dashboard.lastFailure", { reason: lastFailure.reason ?? NONE, time: formatDateTime(lastFailure.finished_at) }) : undefined}
      />
      <StatTile label={t("dashboard.tokens")} value={t("dashboard.tokensValue", { input: n.format(today.input_tokens), output: n.format(today.output_tokens) })} />
    </div>
  );
}

// Usage for one range: totals, the daily chart and the ranked lists
function UsageSection({ days }: { days: UsageDays }) {
  const t = useT();
  const usage = useUsageStats(days);

  if (usage.isPending) return <div className={`${SKELETON} h-96`} aria-label={t("home.loading")} />;
  if (usage.isError) return <Failure message={t(errorKey(usage.error))} onRetry={() => usage.refetch()} />;
  return <UsageBody data={usage.data} />;
}

// The usage numbers once loaded
function UsageBody({ data }: { data: UsageStats }) {
  const t = useT();
  const { lang } = useLanguage();
  const [series, setSeries] = useState<"trips" | "messages">("trips");
  const n = numberFormat(lang);
  const trips = data.trips;
  const ready = countOf(trips.by_status, "ready");
  const failed = countOf(trips.by_status, "failed");
  const averageTrip =
    trips.avg_days === null || trips.avg_travelers === null
      ? NONE
      : t("dashboard.averageTripValue", { days: n.format(trips.avg_days), travelers: n.format(trips.avg_travelers) });

  return (
    <div className="flex flex-col gap-4">
      <div className={GRID}>
        <StatTile label={t("dashboard.newUsers")} value={n.format(data.users.new)} detail={t("dashboard.totalUsers", { count: n.format(data.users.total) })} />
        <StatTile label={t("dashboard.activeUsers")} value={n.format(data.users.active)} />
        <StatTile
          label={t("dashboard.tripsCreated")}
          value={n.format(trips.created)}
          detail={trips.created === 0 ? undefined : t("dashboard.readyFailed", { ready: percent(ready, trips.created, n), failed: percent(failed, trips.created, n) })}
        />
        <StatTile
          label={t("dashboard.chat")}
          value={t("dashboard.chatValue", { conversations: n.format(data.conversations), messages: n.format(data.messages) })}
        />
      </div>

      <section aria-labelledby="dashboard-daily" className={`${CARD} flex flex-col gap-3`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="dashboard-daily" className={TITLE.card}>
            {t("dashboard.perDay")}
          </h3>
          <div className="flex gap-1" role="group" aria-label={t("dashboard.series")}>
            {(["trips", "messages"] as const).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={key === series}
                className={`${BUTTON.ghost} ${key === series ? "bg-accent text-accent-foreground" : ""}`}
                onClick={() => setSeries(key)}
              >
                {t(key === "trips" ? "dashboard.seriesTrips" : "dashboard.seriesMessages")}
              </button>
            ))}
          </div>
        </div>
        <DailyChart
          days={data.daily}
          series={series}
          label={t(series === "trips" ? "dashboard.chartTrips" : "dashboard.chartMessages", { days: data.days })}
          emptyText={t("dashboard.empty")}
          formatDay={(day) => formatDay(day, lang)}
        />
      </section>

      <div className={LIST_GRID}>
        <BarList
          title={t("dashboard.intents")}
          emptyText={t("dashboard.empty")}
          items={data.intents.map((c) => countItem(c, INTENT_KEY[c.key] ? t(INTENT_KEY[c.key] as MessageKey) : c.key, n))}
        />
        <BarList
          title={t("dashboard.destinations")}
          emptyText={t("dashboard.empty")}
          items={data.destinations.map((d) => ({ key: `${d.name}-${d.country}`, label: d.name, value: d.trips, valueText: n.format(d.trips) }))}
          detail={t("dashboard.domesticAbroad", { domestic: n.format(trips.domestic), abroad: n.format(trips.abroad) })}
        />
        <BarList
          title={t("dashboard.tripForms")}
          emptyText={t("dashboard.empty")}
          items={data.trip_forms.map((c) => countItem(c, FORM_KEY[c.key] ? t(FORM_KEY[c.key] as MessageKey) : c.key, n))}
        />
        <StatTile
          label={t("dashboard.averageTrip")}
          value={averageTrip}
          detail={
            trips.median_budget_per_person_vnd === null
              ? undefined
              : t("dashboard.budget", {
                  amount: formatMoney(trips.median_budget_per_person_vnd, "VND", lang),
                  over: trips.with_plan === 0 ? NONE : percent(trips.over_budget, trips.with_plan, n),
                })
          }
        />
        <BarList
          title={t("dashboard.styles")}
          emptyText={t("dashboard.empty")}
          items={data.styles.map((c) => countItem(c, STYLE_KEY[c.key] ? t(STYLE_KEY[c.key] as MessageKey) : c.key, n))}
        />
        <BarList
          title={t("dashboard.models")}
          emptyText={t("dashboard.empty")}
          items={data.models.map((m) => ({
            key: m.model_id,
            label: m.model_id,
            value: m.calls,
            valueText: t("dashboard.modelValue", { calls: n.format(m.calls), errors: percent(m.errors, m.calls, n) }),
          }))}
        />
      </div>
    </div>
  );
}

// An error line with a retry button
function Failure({ message, onRetry }: { message: string; onRetry(): void }) {
  const t = useT();
  return (
    <div className="flex flex-wrap items-center gap-4 text-destructive" role="alert">
      <p>{message}</p>
      <button type="button" className={BUTTON.secondary} onClick={onRetry}>
        {t("common.retry")}
      </button>
    </div>
  );
}

function numberFormat(lang: "en" | "vi"): Intl.NumberFormat {
  return new Intl.NumberFormat(locale(lang), { maximumFractionDigits: 1 });
}

function percent(part: number, whole: number, n: Intl.NumberFormat): string {
  return `${n.format(whole === 0 ? 0 : (part / whole) * 100)}%`;
}

// A duration given in `unit`s per second, shown in seconds, or "-" when there is none
function seconds(value: number | null, unit: number, n: Intl.NumberFormat): string {
  return value === null ? NONE : `${n.format(value / unit)} s`;
}

// Seconds as "40 s" or "12 min"
function duration(s: number, n: Intl.NumberFormat): string {
  return s < S_PER_MIN ? `${n.format(s)} s` : `${n.format(Math.floor(s / S_PER_MIN))} min`;
}

function countOf(counts: StatCount[], key: string): number {
  return counts.find((c) => c.key === key)?.count ?? 0;
}

function countItem(c: StatCount, label: string, n: Intl.NumberFormat) {
  return { key: c.key, label, value: c.count, valueText: n.format(c.count) };
}
