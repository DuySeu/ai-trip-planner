import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import en from "./en.json";
import { LanguageProvider, useLanguage, useT } from "./LanguageProvider.tsx";
import vi from "./vi.json";

// One translated label that also flips the language
function Probe() {
  const t = useT();
  const { lang, setLang } = useLanguage();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "vi" : "en")}>
      {t("nav.myTrips")}
    </button>
  );
}

describe("i18n", () => {
  it("vi_and_en_have_the_same_keys", () => {
    expect(Object.keys(vi).sort()).toEqual(Object.keys(en).sort());
  });

  it("vi_and_en_use_the_same_placeholders", () => {
    const names = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const [key, text] of Object.entries(en)) {
      expect(names(vi[key as keyof typeof vi]), key).toEqual(names(text));
    }
  });

  it("pinned_copy_matches_the_spec", () => {
    expect(en["errors.quota_exhausted"]).toBe("We've hit today's free AI limit. Please try again tomorrow.");
    expect(vi["errors.quota_exhausted"]).toBe("Hôm nay đã hết lượt AI miễn phí. Vui lòng thử lại vào ngày mai.");
    expect([en["form.getIdeas"], vi["form.getIdeas"]]).toEqual(["Not sure where? Get ideas", "Chưa biết đi đâu? Gợi ý cho tôi"]);
    expect([en["suggestion.plan"], vi["suggestion.plan"]]).toEqual(["Plan this trip", "Lên kế hoạch chuyến này"]);
  });

  it("use_t_switches_language_and_persists_it", async () => {
    render(
      <LanguageProvider>
        <Probe />
      </LanguageProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "My trips" }));
    expect(screen.getByRole("button", { name: "Chuyến đi của tôi" })).toBeInTheDocument();
    expect(localStorage.getItem("tripPlanner.lang")).toBe("vi");
    expect(document.documentElement.lang).toBe("vi");
  });
});
