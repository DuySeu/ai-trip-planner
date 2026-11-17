import { Download } from "lucide-react";
import { useState } from "react";
import { readEnvelope, send } from "../api/client.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { type MessageKey, useT } from "../i18n/LanguageProvider.tsx";
import { BANNER, BUTTON } from "../styles/recipes.ts";

const FILENAME = /filename="?([^";]+)"?/;

interface Props {
  tripId: string;
  isDisabled: boolean;
}

// Download GET /trips/{id}/export.xlsx. Fetched rather than linked: an <a download> to another origin
// is a navigation, which the mock worker never sees and browsers ignore `download` for.
export function ExportButton({ tripId, isDisabled }: Props) {
  const t = useT();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<MessageKey | null>(null);

  // Fetch the file and hand it to the browser as a download
  const handleClick = async () => {
    setIsBusy(true);
    setError(null);
    try {
      const response = await send(`/trips/${tripId}/export.xlsx`);
      if (!response.ok) await readEnvelope(response);
      const name = FILENAME.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? "trip.xlsx";
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorKey(err));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <span>
      <button type="button" className={BUTTON.secondary} disabled={isDisabled || isBusy} onClick={handleClick}>
        <Download size={20} strokeWidth={1.75} aria-hidden="true" />
        {t("trip.export")}
      </button>
      {error && (
        <span className={BANNER.error} role="alert">
          {" "}
          {t(error)}
        </span>
      )}
    </span>
  );
}
