import { Compass } from "lucide-react";
import { Link } from "react-router";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON, EMPTY_STATE, TITLE } from "../styles/recipes.ts";

// Any path the app does not know
export function NotFoundPage() {
  const t = useT();
  return (
    <section className={EMPTY_STATE}>
      <Compass size={48} strokeWidth={1.75} aria-hidden="true" />
      <h1 className={TITLE.section}>{t("notFound.title")}</h1>
      <p className="text-muted-foreground">{t("notFound.body")}</p>
      <Link to="/" className={BUTTON.primary}>
        {t("notFound.home")}
      </Link>
    </section>
  );
}
