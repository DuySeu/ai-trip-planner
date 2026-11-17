import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router";
import { LanguageProvider } from "./i18n/LanguageProvider.tsx";
import { AppShell } from "./layout/AppShell.tsx";
import { ChatPage } from "./pages/ChatPage.tsx";
import { HomePage } from "./pages/HomePage.tsx";
import { NamePage } from "./pages/NamePage.tsx";
import { NewTripPage } from "./pages/NewTripPage.tsx";
import { NotFoundPage } from "./pages/NotFoundPage.tsx";
import { createQueryClient } from "./queryClient.ts";
import { TripPage } from "./pages/TripPage.tsx";
import { useSession } from "./session/session.ts";

// The app with its providers and the browser router
export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </LanguageProvider>
    </QueryClientProvider>
  );
}

// Every route; all but /start and unknown paths need a name first
export function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/start"
        element={
          <AppShell hasNav={false}>
            <NamePage />
          </AppShell>
        }
      />
      <Route element={<RequireSession />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/trips/new" element={<NewTripPage />} />
        <Route path="/trips/:tripId" element={<TripPage />} />
        <Route path="/chat/:conversationId?" element={<ChatPage />} />
      </Route>
      <Route path="*" element={<UnknownPath />} />
    </Routes>
  );
}

// Layout route: send a visitor with no name to /start, remembering where they were going
function RequireSession() {
  const session = useSession();
  const location = useLocation();
  if (session === null) {
    return <Navigate to="/start" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  return (
    <AppShell hasNav>
      <Outlet />
    </AppShell>
  );
}

// Not-found page, with the nav when a name is set
function UnknownPath() {
  const session = useSession();
  return (
    <AppShell hasNav={session !== null}>
      <NotFoundPage />
    </AppShell>
  );
}
