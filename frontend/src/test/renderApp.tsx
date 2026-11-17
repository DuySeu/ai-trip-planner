import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import type { Language } from "../api/api.types.ts";
import { AppRoutes } from "../App.tsx";
import { createQueryClient } from "../queryClient.ts";
import { LanguageProvider } from "../i18n/LanguageProvider.tsx";
import { MINH_ID } from "../mocks/fixtures.ts";
import { type Session, saveSession } from "../session/session.ts";

export const MINH: Session = { userId: MINH_ID, name: "Minh" };

// Render the whole app at a path, signed in as Minh unless told otherwise
export function renderApp(path: string | { pathname: string; search?: string; state?: unknown }, opts: { session?: Session | null; lang?: Language; user?: ReturnType<typeof userEvent.setup> } = {}) {
  const session = opts.session === undefined ? MINH : opts.session;
  if (session) saveSession(session);
  const user = opts.user ?? userEvent.setup();
  const queryClient = createQueryClient();
  const result = render(
    <QueryClientProvider client={queryClient}>
      <LanguageProvider initialLang={opts.lang ?? "en"}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
  return { ...result, user, queryClient };
}
