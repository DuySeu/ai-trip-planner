import { useId } from "react";
import type { Tone } from "../pages/dashboardTone.ts";
import { CARD } from "../styles/recipes.ts";

interface Props {
  label: string;
  value: string;
  detail?: string | undefined;
  tone?: Tone;
}

const TONE_CLASS: Record<Tone, string> = {
  ok: CARD,
  warning: "rounded-md border border-warning-foreground/30 bg-warning p-5 text-warning-foreground shadow-surface",
  danger: "rounded-md border border-destructive bg-card p-5 text-card-foreground shadow-surface",
};
const DETAIL_CLASS: Record<Tone, string> = {
  ok: "text-muted-foreground",
  warning: "text-warning-foreground",
  danger: "text-destructive",
};

// One dashboard number with its label and a short detail line; the tone colours the card
export function StatTile({ label, value, detail, tone = "ok" }: Props) {
  const labelId = useId();
  return (
    <div role="group" aria-labelledby={labelId} data-tone={tone} className={`${TONE_CLASS[tone]} flex min-w-0 flex-col gap-1`}>
      <p id={labelId} className="text-sm font-medium">
        {label}
      </p>
      <p className="text-xl font-semibold tracking-tight tabular-nums wrap-anywhere">{value}</p>
      {detail && <p className={`text-sm ${DETAIL_CLASS[tone]} wrap-anywhere`}>{detail}</p>}
    </div>
  );
}
