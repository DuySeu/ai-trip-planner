import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import type { Language } from "../api/api.types.ts";
import { LanguageProvider } from "../i18n/LanguageProvider.tsx";
import { createQueryClient } from "../queryClient.ts";

// Render one component with the app's providers
export function renderWithProviders(ui: ReactNode, lang: Language = "en") {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <LanguageProvider initialLang={lang}>
        <MemoryRouter>{ui}</MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}
