import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { claimUser } from "../api/users.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { type MessageKey, useT } from "../i18n/LanguageProvider.tsx";
import { saveSession } from "../session/session.ts";
import { BUTTON, CARD, FIELD, FIELD_ERROR, INPUT, LABEL, TITLE } from "../styles/recipes.ts";

const MAX_NAME = 50;

// Ask for a name, claim it, then open the page the visitor was heading to
export function NamePage() {
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const [name, setName] = useState("");
  const [fieldError, setFieldError] = useState<MessageKey | null>(null);
  const claim = useMutation({ mutationFn: claimUser });

  const message = fieldError ?? (claim.isError ? errorKey(claim.error) : null);

  // Check the name here first so a blank or long name costs no request
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const clean = name.normalize("NFC").trim();
    if (clean.length === 0) return setFieldError("name.errors.required");
    if (clean.length > MAX_NAME) return setFieldError("name.errors.tooLong");
    setFieldError(null);

    claim.mutate(clean, {
      onSuccess: (user) => {
        saveSession({ userId: user.id, name: user.name });
        const from = (location.state as { from?: string } | null)?.from;
        navigate(from ?? "/", { replace: true });
      },
    });
  };

  return (
    <div className="grid min-h-[calc(100dvh-var(--shell-topbar)-5rem)] place-items-center">
      <form className={`${CARD} flex w-full max-w-[420px] flex-col gap-4`} onSubmit={handleSubmit} noValidate>
        <h1 className={TITLE.page}>{t("name.title")}</h1>
        <p className="text-muted-foreground">{t("name.body")}</p>
        <div className={FIELD}>
          <label className={LABEL} htmlFor="name">
            {t("name.label")}
          </label>
          <input
            id="name"
            className={INPUT}
            value={name}
            autoComplete="nickname"
            aria-invalid={message !== null}
            aria-describedby={message ? "name-error" : undefined}
            onChange={(event) => setName(event.target.value)}
          />
          {message && (
            <p id="name-error" className={FIELD_ERROR} role="alert">
              {t(message)}
            </p>
          )}
        </div>
        <button type="submit" className={BUTTON.primary} disabled={claim.isPending}>
          {t("name.submit")}
        </button>
      </form>
    </div>
  );
}
