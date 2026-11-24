import type { DayCount } from "../api/api.types.ts";

interface Props {
  days: DayCount[];
  series: "trips" | "messages";
  label: string;
  emptyText: string;
  formatDay(day: string): string;
}

const COLUMN = 10;
const GAP = 2;
const HEIGHT = 100;

// One column per day, scaled to the busiest day; hovering a column shows its day and value
export function DailyChart({ days, series, label, emptyText, formatDay }: Props) {
  const max = Math.max(0, ...days.map((d) => d[series]));
  const first = days[0];
  const last = days[days.length - 1];
  return (
    <div className="flex flex-col gap-2">
      {max === 0 && <p className="text-sm text-muted-foreground">{emptyText}</p>}
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${days.length * COLUMN} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-40 w-full text-muted-foreground"
      >
        {days.map((d, i) => {
          const height = max === 0 ? 0 : (d[series] / max) * HEIGHT;
          return (
            <rect key={d.day} x={i * COLUMN + GAP / 2} y={HEIGHT - height} width={COLUMN - GAP} height={height} className="fill-current">
              <title>{`${formatDay(d.day)}: ${d[series]}`}</title>
            </rect>
          );
        })}
      </svg>
      {first && last && (
        <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
          <span>{formatDay(first.day)}</span>
          <span>{formatDay(last.day)}</span>
        </div>
      )}
    </div>
  );
}
