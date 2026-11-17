import { ExternalLink } from "lucide-react";
import type { Plan, PriceBasis } from "../api/api.types.ts";
import { formatMoney, toVnd } from "../format/money.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { BADGE } from "../styles/recipes.ts";

const PRICE = "inline-flex flex-col items-end gap-0.5 tabular-nums whitespace-nowrap";

interface Props {
  amount: string;
  currency: string;
  basis: PriceBasis;
  sourceUrl: string | null;
  currencies: Plan["currencies"];
}

// A price with its basis: a source link when the plan has one, else the Estimate badge; never an invented link
export function Price({ amount, currency, basis, sourceUrl, currencies }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const text = formatMoney(amount, currency, lang);
  const rate = currencies.local_to_home_rate;
  const isLocal = currencies.local !== null && currency === currencies.local && rate !== null;

  if (Number(amount) === 0) return <span className={PRICE}>{t("price.free")}</span>;

  return (
    <span className={PRICE}>
      {basis === "source" && sourceUrl ? (
        <a className="inline-flex items-center gap-1 font-medium text-primary underline underline-offset-3" href={sourceUrl} target="_blank" rel="noopener noreferrer">
          {text}
          <ExternalLink size={14} strokeWidth={1.75} aria-hidden="true" />
        </a>
      ) : (
        <span className="inline-flex items-center gap-2">
          <span className="font-medium">{text}</span>
          <span className={BADGE.warning}>{t("badge.estimate")}</span>
        </span>
      )}
      {isLocal && <span className="text-sm text-muted-foreground">≈ {formatMoney(toVnd(amount, rate), "VND", lang)}</span>}
    </span>
  );
}
