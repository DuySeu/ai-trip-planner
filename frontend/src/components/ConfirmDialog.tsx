import { type ReactNode, useEffect, useId, useRef } from "react";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON, TITLE } from "../styles/recipes.ts";

interface Props {
  isOpen: boolean;
  title: string;
  body?: string;
  confirmLabel: string;
  confirmVariant?: "destructive" | "primary";
  isBusy?: boolean;
  isConfirmDisabled?: boolean;
  children?: ReactNode;
  onConfirm(): void;
  onCancel(): void;
}

// A native modal that asks before an action, optionally with fields; Enter in a field confirms, focus goes back to the trigger on close
export function ConfirmDialog({
  isOpen,
  title,
  body,
  confirmLabel,
  confirmVariant = "destructive",
  isBusy = false,
  isConfirmDisabled = false,
  children,
  onConfirm,
  onCancel,
}: Props) {
  const t = useT();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const id = useId();

  // Open and close the native dialog with the prop, restoring focus afterwards
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !isOpen) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    return () => {
      dialog.close();
      trigger?.focus();
    };
  }, [isOpen]);

  return (
    <dialog
      ref={dialogRef}
      className="m-auto w-[min(440px,calc(100vw-2rem))] flex-col gap-4 rounded-lg border border-border bg-card p-6 text-card-foreground shadow-raised open:flex open:animate-dialog-in"
      aria-labelledby={`${id}-title`}
      aria-describedby={body ? `${id}-body` : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <h2 id={`${id}-title`} className={TITLE.section}>
        {title}
      </h2>
      {body && (
        <p id={`${id}-body`} className="text-muted-foreground">
          {body}
        </p>
      )}
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!isBusy && !isConfirmDisabled) onConfirm();
        }}
      >
        {children}
        <div className="flex flex-wrap justify-end gap-3">
          <button type="button" className={BUTTON.secondary} onClick={onCancel} autoFocus={!children}>
            {t("common.cancel")}
          </button>
          <button type="submit" className={BUTTON[confirmVariant]} disabled={isBusy || isConfirmDisabled}>
            {confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}
