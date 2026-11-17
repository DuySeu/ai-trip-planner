import "../index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { initialTheme, showTheme } from "./theme/theme.ts";

showTheme(initialTheme());

// With VITE_API_MOCK=true every API call is answered in the page from fake data; nothing goes over the network
if (import.meta.env.VITE_API_MOCK === "true") {
  const [{ getResponse }, { handlers }, { mockDb }, { readSession, saveSession }] = await Promise.all([
    import("msw"),
    import("./mocks/handlers.ts"),
    import("./mocks/mockDb.ts"),
    import("./session/session.ts"),
  ]);
  mockDb.reset();

  // The fake data starts over on every load, so a name kept from an earlier load becomes the seeded user
  const session = readSession();
  const [seeded] = mockDb.users;
  if (session && seeded && !mockDb.users.some((u) => u.id === session.userId)) {
    saveSession({ userId: seeded.id, name: seeded.name });
  }

  const networkFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => (await getResponse(handlers, new Request(input, init))) ?? networkFetch(input, init);
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
