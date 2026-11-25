import { Check } from "lucide-react";
import { type FormEvent, useState } from "react";
import type { QuestionnaireMeta } from "../api/api.types.ts";
import { type AnswerBody, useAnswerQuestion } from "../api/conversations.ts";
import { useCurrentLocation } from "../api/location.ts";
import { formatMoney } from "../format/money.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { type MessageKey, type Translate, useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { BANNER, BUTTON, CARD, FIELD, INPUT, LABEL, TEXTAREA, TITLE } from "../styles/recipes.ts";

// The button ids of each step, as the server knows them (src/domain/questionnaire.py OPTIONS)
const STYLES = ["relax", "adventure", "culture", "food", "nature", "nightlife", "shopping"] as const;
const OPTIONS = [
  [],
  ["1", "2", "3_4", "5_plus"],
  ["saver", "moderate", "comfort", "premium"],
  ["hanoi", "hcmc", "danang"],
  ["this_month", "next_month", "holiday_30_4", "holiday_2_9", "holiday_new_year", "christmas"],
  ["2_3", "4_5", "week", "longer"],
] as const;
type OptionId = (typeof OPTIONS)[number][number];
const TOTAL = OPTIONS.length;
// The starting-point step: the visitor's current city comes first, else Hà Nội is preselected
const ORIGIN_STEP = 4;
const FALLBACK_ORIGIN_ID: OptionId = "hanoi";
// What the visitor may type instead of a button, by step
const TYPED: Record<number, { field: string; type: "number" | "text" | "date"; label: MessageKey }> = {
  2: { field: "travelers", type: "number", label: "questionnaire.other2" },
  3: { field: "budget_amount", type: "number", label: "questionnaire.other3" },
  4: { field: "origin", type: "text", label: "questionnaire.other4" },
  5: { field: "start_date", type: "date", label: "questionnaire.other5" },
};
const CHIP =
  "group inline-flex min-h-9 cursor-pointer items-center gap-1 rounded-full border border-input bg-card px-4 text-sm font-medium select-none hover:border-primary disabled:cursor-not-allowed disabled:opacity-50";
const CHIP_ON = "border-primary bg-accent text-accent-foreground";
const CHECKBOX_CHIP = `${CHIP} has-checked:border-primary has-checked:bg-accent has-checked:text-accent-foreground has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring`;

interface Props {
  conversationId: string;
  messageId: string;
  meta: QuestionnaireMeta;
  isBusy: boolean;
  onSuggest(): void;
}

// The six-question card that draws out what the visitor wants, one question at a time; done shows the answers
export function DiscoverQuestionnaire({ conversationId, messageId, meta, isBusy, onSuggest }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const [step, setStep] = useState(Math.min(meta.step + 1, TOTAL));
  const [styles, setStyles] = useState<string[]>(() => {
    const chosen = meta.choices["1"];
    return Array.isArray(chosen) ? chosen : (meta.answers.travel_styles ?? []).filter((s) => (STYLES as readonly string[]).includes(s));
  });
  const [typed, setTyped] = useState("");
  const [notes, setNotes] = useState(meta.answers.notes ?? "");
  const answer = useAnswerQuestion();
  const city = useCurrentLocation().data?.city;
  const isDisabled = isBusy || answer.isPending;
  const chosen = meta.choices[String(step)];
  // On the origin step with no button chosen yet: the current city (or a typed answer equal to it)
  // shows as selected, else Hà Nội does; a press still saves it
  const isOriginOpen = step === ORIGIN_STEP && !chosen;
  const typedOrigin = meta.answers.origin;
  const isCityOn = isOriginOpen && city !== undefined && (typedOrigin ?? city) === city;
  const preselected = isOriginOpen && city === undefined && !typedOrigin ? FALLBACK_ORIGIN_ID : null;

  // Save one answer, then move on; the last step goes straight to the suggestions
  const save = (body: AnswerBody) =>
    answer.mutate(
      { conversationId, messageId, body },
      {
        onSuccess: () => {
          setTyped("");
          if (body.step === TOTAL) onSuggest();
          else setStep(body.step + 1);
        },
      },
    );
  const handleTyped = (event: FormEvent) => {
    event.preventDefault();
    const spec = TYPED[step];
    const value = typed.trim();
    if (!spec || !value) return;
    save({ step, choice: null, answers: { [spec.field]: spec.type === "number" && spec.field === "travelers" ? Number(value) : value } });
  };
  const notesAnswer = () => (notes.trim() ? { notes: notes.trim() } : {});

  if (meta.status === "done") {
    const rows = summary(meta, t, lang);
    // A card closed with no answer (an old question from before the cards) shows only its text
    if (rows.length === 0) return null;
    return (
      <section className={`${CARD} flex w-full flex-col gap-3`} aria-label={t("questionnaire.label")}>
        <h3 className={TITLE.card}>{t("questionnaire.answers")}</h3>
        <dl className="flex flex-col gap-2 text-sm">
          {rows.map(({ question, value }) => (
            <div key={question} className="flex flex-col">
              <dt className="text-muted-foreground">{t(question)}</dt>
              <dd className="font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </section>
    );
  }

  const typedSpec = TYPED[step];
  return (
    <section className={`${CARD} flex w-full flex-col gap-4`} aria-label={t("questionnaire.label")}>
      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-muted-foreground">{t("questionnaire.progress", { step, total: TOTAL })}</p>
        <div className="flex gap-1" aria-hidden="true">
          {OPTIONS.map((_, index) => (
            <span key={index} className={`h-1 flex-1 rounded-full ${index < step ? "bg-primary" : "bg-muted"}`} />
          ))}
        </div>
        <h3 className={TITLE.card}>{t(`questionnaire.q${step}` as MessageKey)}</h3>
      </div>

      {step === 1 ? (
        <fieldset className="flex flex-col gap-3">
          <legend className="sr-only">{t("questionnaire.q1")}</legend>
          <div className="flex flex-wrap gap-2">
            {STYLES.map((style) => (
              <label key={style} className={CHECKBOX_CHIP}>
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={styles.includes(style)}
                  disabled={isDisabled}
                  onChange={() => setStyles((prev) => (prev.includes(style) ? prev.filter((s) => s !== style) : [...prev, style]))}
                />
                <Check size={16} strokeWidth={1.75} aria-hidden="true" className="hidden group-has-checked:inline" />
                {t(`style.${style}`)}
              </label>
            ))}
          </div>
          <button
            type="button"
            className={`${BUTTON.secondary} self-start`}
            disabled={isDisabled || styles.length === 0}
            onClick={() => save({ step: 1, choice: styles, answers: {} })}
          >
            {t("questionnaire.next")}
          </button>
        </fieldset>
      ) : (
        <div className="flex flex-wrap gap-2">
          {step === ORIGIN_STEP && city !== undefined && (
            <button
              type="button"
              className={`${CHIP} ${isCityOn ? CHIP_ON : ""}`}
              aria-pressed={isCityOn}
              disabled={isDisabled}
              onClick={() => save({ step, choice: null, answers: { origin: city } })}
            >
              {isCityOn && <Check size={16} strokeWidth={1.75} aria-hidden="true" />}
              {t("questionnaire.currentCity", { city })}
            </button>
          )}
          {OPTIONS[step - 1]?.map((id: OptionId) => {
            const isOn = chosen === id || preselected === id;
            return (
              <button
                key={id}
                type="button"
                className={`${CHIP} ${isOn ? CHIP_ON : ""}`}
                aria-pressed={isOn}
                disabled={isDisabled}
                onClick={() => save({ step, choice: id, answers: step === TOTAL ? notesAnswer() : {} })}
              >
                {isOn && <Check size={16} strokeWidth={1.75} aria-hidden="true" />}
                {t(`questionnaire.option.${id}`)}
              </button>
            );
          })}
        </div>
      )}

      {typedSpec && (
        <form className="flex items-end gap-2" onSubmit={handleTyped}>
          <div className={`${FIELD} flex-1`}>
            <label className={LABEL} htmlFor={`q-${messageId}-typed`}>
              {t(typedSpec.label)}
            </label>
            <input
              id={`q-${messageId}-typed`}
              type={typedSpec.type}
              inputMode={typedSpec.type === "number" ? "numeric" : undefined}
              min={typedSpec.type === "number" ? 1 : undefined}
              className={`${INPUT} tabular-nums`}
              value={typed}
              disabled={isDisabled}
              onChange={(event) => setTyped(event.target.value)}
            />
          </div>
          <button type="submit" className={BUTTON.secondary} disabled={isDisabled || !typed.trim()}>
            {t("questionnaire.ok")}
          </button>
        </form>
      )}

      {step === TOTAL && (
        <div className={FIELD}>
          <label className={LABEL} htmlFor={`q-${messageId}-notes`}>
            {t("questionnaire.notes")}
          </label>
          <textarea
            id={`q-${messageId}-notes`}
            className={TEXTAREA}
            rows={2}
            value={notes}
            disabled={isDisabled}
            onChange={(event) => setNotes(event.target.value)}
          />
        </div>
      )}

      {answer.isError && (
        <p className={BANNER.error} role="alert">
          {t(errorKey(answer.error))}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {step > 1 && (
          <button type="button" className={BUTTON.ghost} disabled={isDisabled} onClick={() => setStep(step - 1)}>
            {t("questionnaire.back")}
          </button>
        )}
        <button
          type="button"
          className={BUTTON.ghost}
          disabled={isDisabled}
          onClick={() => save({ step, choice: null, answers: step === TOTAL ? notesAnswer() : {} })}
        >
          {t("questionnaire.skip")}
        </button>
        <button type="button" className={`${BUTTON.primary} ml-auto`} disabled={isDisabled} onClick={onSuggest}>
          {t("questionnaire.suggestNow")}
        </button>
      </div>
    </section>
  );
}

// The answered questions of a done card: the label of the pressed button, else the value from the draft
function summary(meta: QuestionnaireMeta, t: Translate, lang: "en" | "vi"): { question: MessageKey; value: string }[] {
  const a = meta.answers;
  const typed = [
    a.travel_styles?.length ? a.travel_styles.map((s) => t(`style.${s}`)).join(", ") : null,
    a.travelers != null ? t("questionnaire.people", { count: a.travelers }) : null,
    a.budget_amount != null ? formatMoney(a.budget_amount, "VND", lang) : null,
    a.origin ?? null,
    a.start_date ?? a.month ?? null,
    [a.length_days != null ? t("questionnaire.days", { count: a.length_days }) : null, a.notes].filter(Boolean).join(" · ") || null,
  ];
  return typed.flatMap((fallback, index) => {
    const choice = meta.choices[String(index + 1)];
    const value =
      index === 0 && Array.isArray(choice)
        ? choice.map((s) => t(`style.${s}` as MessageKey)).join(", ")
        : typeof choice === "string"
          ? [t(`questionnaire.option.${choice}` as MessageKey), index === TOTAL - 1 ? a.notes : null].filter(Boolean).join(" · ")
          : fallback;
    return value ? [{ question: `questionnaire.q${index + 1}` as MessageKey, value }] : [];
  });
}
