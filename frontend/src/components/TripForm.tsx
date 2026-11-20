import { Check, Lightbulb } from "lucide-react";
import { type FormEvent, useState } from "react";
import { TRAVEL_STYLES, type TravelStyle } from "../api/api.types.ts";
import type { ApiError } from "../api/client.ts";
import { addDays, locale, todayInVietnam } from "../format/dates.ts";
import { COUNTRY_CURRENCY } from "../format/money.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { type MessageKey, useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { PlaceSearch } from "./PlaceSearch.tsx";
import { BANNER, BUTTON, CARD, FIELD, FIELD_ERROR, HELP, INPUT, LABEL, TEXTAREA } from "../styles/recipes.ts";
import { type TripFormErrors, type TripFormValues, validateTripForm } from "./validateTripForm.ts";

const MAX_TRIP_DAYS = 30;
const MAX_TRAVELERS = 50;
const PAIR = "grid grid-cols-1 gap-4 sm:grid-cols-2";
const FIELDSET = "flex min-w-0 flex-col gap-2";
const LEGEND = `${LABEL} mb-2`;
const CHIP =
  "group inline-flex min-h-9 cursor-pointer items-center gap-1 rounded-full border border-input bg-card px-4 text-sm font-medium select-none hover:border-primary has-checked:border-primary has-checked:bg-accent has-checked:text-accent-foreground has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring";
const CHIP_CHECK = "hidden group-has-checked:inline";

interface Props {
  initialValues: TripFormValues;
  initialErrors?: TripFormErrors;
  isBare?: boolean;
  submit: { isPending: boolean; error: ApiError | null };
  submitLabel?: MessageKey;
  onSubmit(values: TripFormValues): void;
  onGetIdeas?(values: TripFormValues): void;
  onCancel?(): void;
}

// The trip request form: checks the backend's rules locally, then hands valid values up
export function TripForm({
  initialValues,
  initialErrors = {},
  isBare = false,
  submit,
  submitLabel = "form.submit",
  onSubmit,
  onGetIdeas,
  onCancel,
}: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const [values, setValues] = useState(initialValues);
  const [hasTried, setHasTried] = useState(false);
  const [hintStyle, setHintStyle] = useState<TravelStyle | null>(null);

  const today = todayInVietnam();
  const errors = hasTried ? validateTripForm(values, today) : initialErrors;
  const country = values.destination?.country_code;
  const localCurrency = country && country !== "VN" ? COUNTRY_CURRENCY[country] : undefined;
  const budgetDisplay = values.budget_amount ? new Intl.NumberFormat(locale(lang)).format(Number(values.budget_amount)) : "";
  const submitKey = submit.error ? errorKey(submit.error) : null;
  const isQuota = submit.error?.code === "quota_exhausted" || submit.error?.code === "rate_limited";

  // Replace one field
  const set = <K extends keyof TripFormValues>(key: K, value: TripFormValues[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  // Add or remove one travel style
  const toggleStyle = (style: TravelStyle) =>
    setValues((prev) => ({
      ...prev,
      travel_styles: prev.travel_styles.includes(style)
        ? prev.travel_styles.filter((x) => x !== style)
        : [...prev.travel_styles, style],
    }));

  // Validate everything; on errors move focus to the first broken field
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setHasTried(true);
    const found = validateTripForm(values, today);
    const first = Object.keys(found)[0];
    if (first) {
      document.getElementById(`trip-${first}`)?.focus();
      return;
    }
    onSubmit(values);
  };

  // Props shared by every field with an error slot
  const describe = (key: keyof TripFormValues) => ({
    "aria-invalid": errors[key] !== undefined,
    "aria-describedby": errors[key] ? `trip-${key}-error` : undefined,
  });
  const errorFor = (key: keyof TripFormValues) => {
    const message = errors[key];
    return message ? (
      <p id={`trip-${key}-error`} className={FIELD_ERROR}>
        {t(message)}
      </p>
    ) : null;
  };

  return (
    <form className={`${isBare ? "" : CARD} flex flex-col gap-5`} onSubmit={handleSubmit} noValidate>
      <div className={FIELD}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <label className={LABEL} htmlFor="trip-destination">
            {t("form.destination")}
          </label>
          {onGetIdeas && (
            <button type="button" className="inline-flex cursor-pointer items-center gap-1 text-sm font-medium text-primary underline underline-offset-3" onClick={() => onGetIdeas(values)}>
              <Lightbulb size={16} strokeWidth={1.75} aria-hidden="true" />
              {t("form.getIdeas")}
            </button>
          )}
        </div>
        <PlaceSearch
          inputId="trip-destination"
          value={values.destination}
          isInvalid={errors.destination !== undefined}
          describedBy={errors.destination ? "trip-destination-error" : localCurrency ? "trip-currency-hint" : undefined}
          onChange={(place) => set("destination", place)}
        />
        {errorFor("destination")}
        {localCurrency && (
          <p id="trip-currency-hint" className={HELP}>
            {t("form.abroadHint", { currency: localCurrency })}
          </p>
        )}
      </div>

      <div className={FIELD}>
        <label className={LABEL} htmlFor="trip-origin">
          {t("form.origin")}
        </label>
        <input
          id="trip-origin"
          className={INPUT}
          value={values.origin}
          placeholder={t("form.originPlaceholder")}
          maxLength={200}
          onChange={(event) => set("origin", event.target.value)}
        />
      </div>

      <div className={PAIR}>
        <div className={FIELD}>
          <label className={LABEL} htmlFor="trip-start_date">
            {t("form.startDate")}
          </label>
          <input
            id="trip-start_date"
            type="date"
            className={`${INPUT} tabular-nums`}
            min={today}
            value={values.start_date}
            onChange={(event) => set("start_date", event.target.value)}
            {...describe("start_date")}
          />
          {errorFor("start_date")}
        </div>
        <div className={FIELD}>
          <label className={LABEL} htmlFor="trip-end_date">
            {t("form.endDate")}
          </label>
          <input
            id="trip-end_date"
            type="date"
            className={`${INPUT} tabular-nums`}
            min={values.start_date || today}
            max={values.start_date ? addDays(values.start_date, MAX_TRIP_DAYS - 1) : undefined}
            value={values.end_date}
            onChange={(event) => set("end_date", event.target.value)}
            {...describe("end_date")}
          />
          {errorFor("end_date")}
        </div>
      </div>

      <div className={PAIR}>
        <div className={FIELD}>
          <label className={LABEL} htmlFor="trip-travelers">
            {t("form.travelers")}
          </label>
          <input
            id="trip-travelers"
            type="number"
            inputMode="numeric"
            className={`${INPUT} tabular-nums`}
            min={1}
            max={MAX_TRAVELERS}
            value={Number.isNaN(values.travelers) ? "" : values.travelers}
            onChange={(event) => set("travelers", event.target.valueAsNumber)}
            {...describe("travelers")}
          />
          {errorFor("travelers")}
        </div>
      </div>

      <fieldset className={FIELDSET} aria-describedby={errors.travel_styles ? "trip-travel_styles-error" : undefined}>
        <legend className={LEGEND}>{t("form.styles")}</legend>
        <div className="flex flex-wrap gap-2">
          {TRAVEL_STYLES.map((style, index) => (
            <label
              key={style}
              className={CHIP}
              onPointerEnter={() => setHintStyle(style)}
              onFocus={() => setHintStyle(style)}
            >
              <input
                id={index === 0 ? "trip-travel_styles" : undefined}
                type="checkbox"
                className="sr-only"
                checked={values.travel_styles.includes(style)}
                aria-describedby={`trip-style-${style}-hint`}
                onChange={() => toggleStyle(style)}
              />
              <Check size={16} strokeWidth={1.75} aria-hidden="true" className={CHIP_CHECK} />
              {t(`style.${style}`)}
            </label>
          ))}
        </div>
        <div hidden>
          {TRAVEL_STYLES.map((style) => (
            <span key={style} id={`trip-style-${style}-hint`}>
              {t(`styleHint.${style}`)}
            </span>
          ))}
        </div>
        <p className={`${HELP} min-h-10`} aria-hidden="true">
          {hintStyle ? (
            <>
              <span className="font-medium text-foreground">{t(`style.${hintStyle}`)}:</span> {t(`styleHint.${hintStyle}`)}
            </>
          ) : (
            t("form.stylesHint")
          )}
        </p>
        {errorFor("travel_styles")}
      </fieldset>

      <div className={PAIR}>
        <div className={FIELD}>
          <label className={LABEL} htmlFor="trip-budget_amount">
            {t("form.budget")}
          </label>
          <input
            id="trip-budget_amount"
            className={`${INPUT} tabular-nums`}
            inputMode="numeric"
            autoComplete="off"
            value={budgetDisplay}
            onChange={(event) => set("budget_amount", event.target.value.replace(/\D/g, "").replace(/^0+(?=\d)/, ""))}
            {...describe("budget_amount")}
          />
          {errorFor("budget_amount")}
        </div>
        <fieldset className={FIELDSET}>
          <legend className={LEGEND}>{t("form.budgetScope")}</legend>
          <div className="flex min-h-11 flex-wrap items-center gap-4">
            {(["per_person", "total"] as const).map((scope) => (
              <label key={scope} className="inline-flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  className="size-5 accent-primary"
                  name="budget_scope"
                  value={scope}
                  checked={values.budget_scope === scope}
                  onChange={() => set("budget_scope", scope)}
                />
                {t(scope === "per_person" ? "form.perPerson" : "form.total")}
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <div className={FIELD}>
        <label className={LABEL} htmlFor="trip-notes">
          {t("form.notes")}
        </label>
        <textarea
          id="trip-notes"
          className={TEXTAREA}
          rows={3}
          placeholder={t("form.notesPlaceholder")}
          value={values.notes}
          onChange={(event) => set("notes", event.target.value)}
          {...describe("notes")}
        />
        {errorFor("notes")}
      </div>

      {submitKey && (
        <p className={isQuota ? BANNER.warning : BANNER.error} role="alert">
          {t(submitKey)}
        </p>
      )}
      <div className="flex flex-col gap-3 sm:flex-row">
        <button type="submit" className={BUTTON.primary} disabled={submit.isPending}>
          {t(submitLabel)}
        </button>
        {onCancel && (
          <button type="button" className={BUTTON.secondary} onClick={onCancel}>
            {t("chat.tripForm.cancel")}
          </button>
        )}
      </div>
    </form>
  );
}
