import { useId } from "react";
import { CARD, TITLE } from "../styles/recipes.ts";

interface Item {
  key: string;
  label: string;
  value: number;
  valueText: string;
}

interface Props {
  title: string;
  items: Item[];
  emptyText: string;
  detail?: string | undefined;
}

// A ranked list with a horizontal bar per row, each bar a share of the largest value
export function BarList({ title, items, emptyText, detail }: Props) {
  const titleId = useId();
  const max = Math.max(0, ...items.map((item) => item.value));
  return (
    <section aria-labelledby={titleId} className={`${CARD} flex min-w-0 flex-col gap-3`}>
      <h3 id={titleId} className={TITLE.card}>
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((item) => (
            <li key={item.key} className="flex flex-col gap-1">
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="min-w-0 wrap-anywhere">{item.label}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">{item.valueText}</span>
              </div>
              <div className="h-2 rounded-full bg-muted">
                <div className="h-2 rounded-full bg-muted-foreground" style={{ width: `${max === 0 ? 0 : (item.value / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {detail && <p className="text-sm text-muted-foreground">{detail}</p>}
    </section>
  );
}
