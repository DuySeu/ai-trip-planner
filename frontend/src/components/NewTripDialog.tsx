import { X } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON, TITLE } from "../styles/recipes.ts";
import { NewTripForm } from "./NewTripForm.tsx";

interface Props {
  isOpen: boolean;
  onClose(): void;
}

// The new-trip form in a native modal; the form mounts fresh on every open, focus goes back to the trigger on close
export function NewTripDialog({ isOpen, onClose }: Props) {
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
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(var(--shell-reading),calc(100vw-2rem))] flex-col overflow-y-auto overscroll-contain rounded-lg border border-border bg-card text-card-foreground shadow-raised open:flex open:animate-dialog-in"
      aria-labelledby={`${id}-title`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-border bg-card py-3 pr-3 pl-5">
        <h2 id={`${id}-title`} className={TITLE.section}>
          {t("form.title")}
        </h2>
        <button type="button" className={BUTTON.icon} aria-label={t("common.close")} onClick={onClose}>
          <X size={20} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </header>
      {isOpen && (
        <div className="flex flex-col gap-4 p-5">
          <NewTripForm conversationId={null} place={null} isMissingPlace={false} isBare />
        </div>
      )}
    </dialog>
  );
}
