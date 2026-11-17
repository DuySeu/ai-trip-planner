# Web frontend implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the whole `web/` app (all five pages and every visitor-facing feature in `REQUIREMENTS.md`) against a mock backend that speaks the exact API contract, so it runs end to end today and switches to the real FastAPI backend by changing one env var.

**Architecture:** React + TypeScript on Vite, plain CSS (global tokens from `docs/index.css` + one CSS module per component). All server data goes through typed fetch functions in `web/src/api/` and React Query hooks; nothing in a page calls `fetch` directly. Mock Service Worker (MSW) answers those same requests from an in-memory store seeded with hardcoded fixtures, in the browser (`VITE_API_MOCK=true`) and in tests (`msw/node`). The chat uses `POST` + a streamed `text/event-stream` body read with `fetch` and a small SSE parser (`EventSource` cannot `POST`).

**Tech Stack:** Node 24, pnpm, React 19, React Router 7, TanStack Query 5, Vite, TypeScript (strict), Vitest + React Testing Library + user-event + jsdom, MSW 2, lucide-react, Biome (lint + format). Exact versions are whatever is current at install time and are pinned by `pnpm-lock.yaml`.

**Spec:** `docs/superpowers/specs/2026-11-16-ai-trip-planner-design.md` (sections "Data flow", "Plan document", "API", "Validation rules", "Free quota running out"), `REQUIREMENTS.md`, the design guide `docs/DESIGN.md` (read in full before any UI task), and the backend plan `docs/superpowers/plans/2026-11-16-backend-core.md` Tasks 18 to 22 (response envelope, SSE events).

**Out of scope:** backend code, login, any Excel generation in the browser (the export is a backend download; the mock returns a placeholder file).

## Global constraints

- All code under `web/`. Nothing in `src/`, `sql/` or `tests/` changes. No commit steps: the folder is not a git repo, and the user commits only when they ask. Each task ends at "tests pass".
- Follow the coding-style skill (`~/.claude/skills/coding-style/SKILL.md`, `references/typescript.md`, `references/react.md`): no `any`, named exports, `import type`, discriminated unions for async state, header comment above every function and component, no single-use subcomponents or hooks, keys from data ids, `<button>` / `<a>` / `<form>` / `<dialog>` semantics, every input labelled.
- `tsconfig.json`: the strict set from `references/typescript.md` with `module: "esnext"`, `moduleResolution: "bundler"`, `jsx: "react-jsx"`, plus `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `erasableSyntaxOnly` (so no `enum`; use string-literal unions).
- Design guide is law (`docs/DESIGN.md`): `web/src/styles/tokens.css` is a byte-for-byte copy of `docs/index.css`; no hex, `rgb(` or literal `border-radius` / `box-shadow` / font family in any component CSS; both light and dark; Lucide icons only, sizes 20 / 16; Be Vietnam Pro + JetBrains Mono from Google Fonts (`vietnamese,latin` subsets); `.dark` on `<html>`; motion rules of section 6.
- Every UI string comes from `web/src/i18n/en.json` (default) and `vi.json`; the two files have the same keys. The UI language is kept in `localStorage` key `tripPlanner.lang`, the theme in `tripPlanner.theme`, the session in `tripPlanner.session`.
- Exact copy pinned by the spec: quota message EN "We've hit today's free AI limit. Please try again tomorrow.", VI "Hôm nay đã hết lượt AI miễn phí. Vui lòng thử lại vào ngày mai."; the form link EN "Not sure where? Get ideas", VI "Chưa biết đi đâu? Gợi ý cho tôi"; card button EN "Plan this trip", VI "Lên kế hoạch chuyến này".
- Input limits mirrored from the backend (the backend stays the authority, the UI only saves a round trip): name 1 to 50 chars after trim; travelers 1 to 50; `budget_amount` > 0 VND; `start_date` >= today in `Asia/Ho_Chi_Minh`; `end_date >= start_date`; at most 30 days counting both ends; at least one travel style; destination only from the place search; notes <= 2000; chat message 1 to 4000 chars after trim.
- Polling: `GET /trips/{id}` every 2000 ms while `status` is `queued`, `researching` or `planning`; no polling otherwise.
- Money values arrive as decimal strings (pydantic `Decimal`); never do arithmetic on them except the display-only `≈ VND` conversion line. Format with `Intl.NumberFormat(lang === "vi" ? "vi-VN" : "en-US", { style: "currency", currency, maximumFractionDigits: currency === "VND" ? 0 : 2 })`.
- Plain punctuation in code, copy and docs: `-`, straight quotes, `...`.

## API contract the client codes against

These are the shapes the backend plan implies but does not spell out. They live in one file, `web/src/api/api.types.ts`; if backend Tasks 21 and 22 pick different field names, only that file and the mock fixtures change. Field names are snake_case, as FastAPI returns them.

- Base URL: `import.meta.env.VITE_API_BASE_URL` (default `http://localhost:8000`, which the backend's `CORS_ORIGINS` default `http://localhost:5173` already allows). No `/api` prefix.
- Envelope (backend Task 20): `ApiResponse<T> = { success: boolean; data: T | null; error: { code: string; message: string } | null; meta: { total: number; limit: number; offset: number } | null }`. `204` has no body. The export route returns the file, not an envelope.
- `User { id; name; created_at; trip_count }`.
- `Place { name; country_code; country; admin1: string | null; lat; lon }` (from Open-Meteo geocoding).
- `TripStatus = "queued" | "researching" | "planning" | "ready" | "failed"`. `Trip` = every `trips` column except `expires_at` and `model_id`, plus `stage: "researching" | "planning" | "validating" | null`, `plan: Plan | null` and `sources: Record<string, { title: string; url: string | null }>` (the trip's `research_results` keyed by id, so a `source_id` resolves to a link; the backend plan does not return these yet, so backend Task 21 has to add it). `TripSummary` = `Trip` without `plan`, `notes`, `origin` (for `GET /users/{id}/trips`).
- `Plan` and its parts exactly as spec "Plan document" (`PlanItem` adds `option_id: string | null`).
- `CreateTripBody { user_id; conversation_id: string | null; destination: { name; country_code; lat; lon }; origin; start_date; end_date; travelers; group_type; travel_styles; transport_modes; budget_amount: string; budget_scope; language; notes: string | null }`.
- `RequestDraft` = every `CreateTripBody` field except `user_id` / `conversation_id` optional, plus `month: string | null`, `length_days: number | null`.
- `Conversation { id; user_id; title: string | null; request_draft: RequestDraft | null; created_at; updated_at }`; `GET /conversations/{id}` returns `Conversation & { messages: Message[] }`.
- `Message { id; role: "user" | "assistant"; content; intent: MessageIntent | null; suggestions: SuggestionCard[] | null; created_at }`.
- `SuggestionCard { name; country_code; why; length_days; est_cost_per_person_vnd: string; best_months: string[]; highlights: string[]; source_ids: number[] }` (backend Task 19).
- SSE (backend Task 18): frames `event: <type>\ndata: <json>\n\n`; `token {text}`, `plan {plan_revision}`, `suggestions {cards}`, `error {code, message, blocked_until?}`, `done {}`. Errors raised before streaming (404, 409, 422, 429) come back as a normal JSON envelope with that status.

## Review focus

1. A chunk boundary falls inside an SSE frame or inside a Vietnamese multi-byte character ("Đà Lạt" split between two reads). The parser must buffer and decode with `TextDecoder(..., { stream: true })`, never emit a half frame or a replacement character. Test in Task 2.
2. At 00:30 in Vietnam the browser in UTC (or a laptop set to another zone) still thinks it is yesterday; the date picker's minimum and the "start in the past" check use `todayInVietnam()`, not `new Date()`. Test in Task 4.
3. The visitor edits from the chat while looking at revision 3 and another tab already saved revision 4: the `409` must reload the trip, show "This plan changed, here is the latest version", and keep the typed message in the composer. Test in Task 10.
4. A re-plan (dates changed in chat) moves a `ready` trip back to `researching` with its old plan still present: the page keeps showing the plan and export, shows the progress card above it, keeps the chat open for questions, and polls until `ready`. Test in Task 8.
5. The visitor leaves the trip page mid-poll or mid-stream: polling stops and the stream is aborted with `AbortController`, no state update after unmount, no second request when they come back. Test in Tasks 8 and 10.

---

### Task 1: Scaffold, tokens, test harness

**Files:**

- Create: `web/package.json`, `web/pnpm-lock.yaml` (generated), `web/tsconfig.json`, `web/vite.config.ts`, `web/biome.json`, `web/index.html`, `web/.env.example`, `web/src/main.tsx`, `web/src/App.tsx`
- Create: `web/src/styles/tokens.css` (copy of `docs/index.css`), `web/src/styles/base.css`
- Create: `web/src/test/setup.ts`, `web/src/styles/tokens.test.ts`

**Interfaces:**

- Produces: `App` (renders the router; Task 5 fills the routes), scripts `pnpm dev`, `pnpm build`, `pnpm test` (`vitest run`), `pnpm lint` (`biome check .`), `pnpm typecheck` (`tsc -b --noEmit`).
- Produces: `web/.env.example` with `VITE_API_BASE_URL=http://localhost:8000` and `VITE_API_MOCK=true`.

- [ ] **Step 1: Create the app:** `cd web && pnpm create vite@latest . --template react-ts`, then `pnpm add react-router @tanstack/react-query lucide-react` and `pnpm add -D vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom msw @biomejs/biome`. Delete the template's demo assets, `App.css` and `index.css`.
- [ ] **Step 2: Configure.** `vite.config.ts` sets `test: { environment: "jsdom", setupFiles: ["src/test/setup.ts"], globals: false }` and `server.port: 5173`. `index.html` loads Google Fonts `Be Vietnam Pro:wght@400;500;600;700` and `JetBrains Mono:wght@400;500` with `&subset=vietnamese` and `display=swap`, sets `<html lang="en">`. `base.css`: box-sizing reset; `body` uses `--background`, `--foreground`, `--font-sans`, 16px/24px; `:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px }`; `@media (prefers-reduced-motion: reduce)` turns transitions and animations off. `main.tsx` imports `tokens.css` then `base.css`.
- [ ] **Step 3: Write the failing test** in `web/src/styles/tokens.test.ts`:

```ts
it("tokens_css_matches_design_guide", () => {
  const guide = readFileSync(resolve(__dirname, "../../../docs/index.css"), "utf8");
  const app = readFileSync(resolve(__dirname, "tokens.css"), "utf8");
  expect(app).toBe(guide);
});

it("component_css_has_no_literal_colours", () => {
  const offenders = globSync("src/**/*.module.css").filter((f) => /#[0-9a-f]{3,8}\b|rgba?\(/i.test(readFileSync(f, "utf8")));
  expect(offenders).toEqual([]);
});
```

- [ ] **Step 4: Run** `pnpm test`; expect the first test to FAIL until `tokens.css` is copied, then copy it (`cp ../docs/index.css src/styles/tokens.css`).
- [ ] **Step 5: Run** `pnpm test && pnpm lint && pnpm typecheck && pnpm build`; expect all to pass.

---

### Task 2: API types, client, SSE parser

**Files:**

- Create: `web/src/api/api.types.ts`, `web/src/api/client.ts`, `web/src/api/parseSse.ts`
- Test: `web/src/api/client.test.ts`, `web/src/api/parseSse.test.ts`

**Interfaces:**

- Produces in `api.types.ts`: every type in "API contract the client codes against", plus the literal unions `GroupType` (`solo`, `couple`, `family`, `friends`, `colleagues`), `TravelStyle` (`relax`, `adventure`, `culture`, `food`, `nature`, `nightlife`, `shopping`, `luxury`, `budget`), `TransportMode` (`flight`, `train`, `bus`, `car`, `motorbike`, `boat`), `BudgetScope` (`per_person`, `total`), `Language` (`en`, `vi`), `Category`, `PriceBasis`, `ItemStatus`, `MessageIntent`, `ChatEvent` (discriminated on `type`: `token` / `plan` / `suggestions` / `error` / `done`). Each union also exported as an `as const` array (`GROUP_TYPES`, `TRAVEL_STYLES`, `TRANSPORT_MODES`) for the form.
- Produces in `client.ts`: `class ApiError extends Error { status: number; code: string; blockedUntil: string | null }`; `apiRequest<T>(path: string, init?: RequestInit): Promise<{ data: T; meta: PageMeta | null }>` (prefixes `VITE_API_BASE_URL`, sends and accepts JSON, unwraps the envelope, throws `ApiError` from the envelope's `error`; a non-JSON or network failure throws `ApiError` with `code: "network_error"` and `status: 0`; `204` resolves `data: null`); `apiUrl(path: string): string` (for the export link).
- Produces in `parseSse.ts`: `parseSse(body: ReadableStream<Uint8Array>, signal: AbortSignal): AsyncGenerator<ChatEvent>`.

- [ ] **Step 1: Write the failing tests:**

```ts
it("emits_one_event_when_a_frame_is_split_across_chunks", async () => {
  const events = await collect(streamOf(["event: tok", "en\ndata: {\"text\":\"Hi\"}\n", "\n"]));
  expect(events).toEqual([{ type: "token", data: { text: "Hi" } }]);
});

it("decodes_vietnamese_split_inside_a_multibyte_character", async () => {
  const bytes = new TextEncoder().encode('event: token\ndata: {"text":"Đà Lạt"}\n\n');
  const events = await collect(byteStreamOf([bytes.slice(0, 29), bytes.slice(29)]));   // byte 29 is inside "Đ"
  expect(events[0]).toEqual({ type: "token", data: { text: "Đà Lạt" } });
});

it("ignores_comment_lines_and_unknown_event_types", async () => { ... });
it("stops_when_the_signal_aborts", async () => { ... });

it("api_request_throws_api_error_with_envelope_code", async () => {
  server.use(http.post(`${BASE}/trips`, () => HttpResponse.json(
    { success: false, data: null, error: { code: "quota_exhausted", message: "x" }, meta: null }, { status: 429 })));
  await expect(apiRequest("/trips", { method: "POST", body: "{}" })).rejects.toMatchObject({ status: 429, code: "quota_exhausted" });
});

it("api_request_maps_html_502_to_network_error", async () => { ... });
it("api_request_resolves_null_on_204", async () => { ... });
```

- [ ] **Step 2: Run** `pnpm test src/api`; expect FAIL (modules missing).
- [ ] **Step 3: Implement** `apiRequest`, `ApiError`, `apiUrl`, `parseSse`. The parser keeps a string buffer, splits on `\n\n`, reads `event:` and `data:` lines, `JSON.parse`s data, and drops frames whose type is not a `ChatEvent` type. `blockedUntil` comes from the error event's `blocked_until` or is parsed from the 429 message only if the backend adds a field; until then it is `null`.
- [ ] **Step 4: Run** `pnpm test src/api`; expect PASS.

---

### Task 3: Mock backend with hardcoded fixtures

**Files:**

- Create: `web/src/mocks/fixtures.ts`, `web/src/mocks/mockDb.ts`, `web/src/mocks/handlers.ts`, `web/src/mocks/chatScript.ts`, `web/src/mocks/browser.ts`, `web/src/mocks/server.ts`
- Create: `web/public/mockServiceWorker.js` (generated by `pnpm exec msw init public`)
- Modify: `web/src/main.tsx` (start the worker before rendering when `VITE_API_MOCK === "true"`), `web/src/test/setup.ts` (start `server`, reset `mockDb` and handlers after each test)
- Test: `web/src/mocks/handlers.test.ts`

**Interfaces:**

- Produces in `fixtures.ts`: `PLACES: Place[]` (Hà Nội, Hồ Chí Minh, Đà Nẵng, Đà Lạt, Hội An, Phú Quốc, Sa Pa, Bangkok TH, Chiang Mai TH, Singapore SG, Tokyo JP, Seoul KR, Paris FR), `planDomestic(start: string, days: number): Plan` (Đà Lạt, all VND, one `typical` weather day, one `source` price with a URL, transport options for both legs with one chosen each, a `local` leg), `planAbroad(start, days): Plan` (Bangkok, THB rate `720.5` dated `2026-11-16`, mixed VND flight and THB ground prices, an `over_budget` warning), `SOURCES: Record<number, { title: string; url: string }>`, `SUGGESTION_CARDS: SuggestionCard[]` (3 cards, one abroad).
- Produces in `mockDb.ts`: `mockDb` with `reset(now?: () => Date)`, `setNow(now: () => Date)`, `setQuotaBlockedUntil(iso: string | null)`, `bumpRevision(tripId: string)` (simulates a save from another tab), and the tables `users`, `trips`, `conversations`, `messages` as plain arrays. Seed on reset: user "Minh" with a ready domestic trip, a ready abroad trip, a `failed` trip with `failure_reason: "quota_exhausted"`, and one conversation holding a `suggest` reply with `SUGGESTION_CARDS`.
- Produces in `handlers.ts`: `handlers` covering every route in spec "API" except `/health` and `/ready`, with the errors listed there. Behaviour pinned here:
  - `POST /users` matches on `name.normalize("NFC").trim().toLowerCase()`; returns the existing user or creates one.
  - `POST /trips` checks the validation rules (422 `invalid_request` with the first failing rule as message), the quota block (429 `quota_exhausted`), creates a `queued` trip with `plan: null`. Status is derived from elapsed time on every `GET /trips/{id}`: `queued` < 2 s, `researching` < 6 s, `planning` < 10 s, then `ready` with `planDomestic` or `planAbroad` by country and `plan_revision: 1`. A trip whose `notes` contain `#fail` ends `failed` with `failure_reason: "llm_budget_exceeded"` instead.
  - `POST /trips/{id}/retry` 409 when not `failed`; else restarts the clock. `DELETE` 204. `GET /trips/{id}/export.xlsx` 409 while `plan` is null, else a small `Blob` with type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` and `Content-Disposition: attachment; filename="<ascii destination>.xlsx"`.
  - `GET /places` 422 under 2 chars, else case- and accent-insensitive prefix match on `PLACES`, max 10.
  - `POST /conversations/{id}/messages`: 404 when `trip_id` is not the user's, 409 `conflict` when `plan_revision` differs from the trip's, 409 when the trip has no plan yet, 429 on quota; else a `ReadableStream` that writes the frames from `chatScript` with a 30 ms gap between tokens.
- Produces in `chatScript.ts`: `scriptReply(input: { content: string; trip: Trip | null; conversation: Conversation }): { events: ChatEvent[]; updatedTrip: Trip | null }`. Rules, first match wins: content matches `/where|ideas|gợi ý|đi đâu/i` and no trip -> `suggest` (tokens, then `suggestions` with `SUGGESTION_CARDS`); trip set and content matches `/change|switch|cheaper|đổi|thay/i` -> swap the chosen outbound transport option and its day-1 item, bump `plan_revision`, emit `plan` then tokens "Done. Changed: ..."; content matches `/date|ngày|people|người/i` with a trip -> set trip status `researching` (re-plan, plan kept) and tokens "Re-planning started"; otherwise a 3-sentence answer in the language of the message (Vietnamese when it contains a Vietnamese diacritic). Always ends with `done`.

- [ ] **Step 1: Write the failing tests** (they call the Task 2 client, so the mock is tested through the real contract):

```ts
it("claim_user_ignores_case_spaces_and_unicode_form", async () => {
  const a = await apiRequest<User>("/users", post({ name: " Đức " }));
  const b = await apiRequest<User>("/users", post({ name: "ĐỨC".normalize("NFD") }));
  expect(b.data.id).toBe(a.data.id);
});

it("created_trip_moves_from_queued_to_ready_with_the_clock", async () => {
  let t = 0; mockDb.setNow(() => new Date(BASE_TIME + t));
  const { data } = await apiRequest<Trip>("/trips", post(validBody()));
  expect((await getTrip(data.id)).status).toBe("queued");
  t = 3000;  expect((await getTrip(data.id)).status).toBe("researching");
  t = 11000; expect((await getTrip(data.id))).toMatchObject({ status: "ready", plan_revision: 1 });
});

it("create_trip_rejects_31_day_trip_with_422", async () => { ... });
it("create_trip_returns_429_quota_exhausted_while_blocked", async () => { ... });
it("message_with_stale_plan_revision_returns_409_json", async () => { ... });
it("edit_message_streams_plan_event_before_tokens_and_bumps_revision", async () => { ... });
it("places_search_matches_without_accents", async () => {
  expect((await apiRequest<Place[]>("/places?q=da lat")).data[0]?.name).toBe("Đà Lạt");
});
```

- [ ] **Step 2: Run** `pnpm test src/mocks`; expect FAIL.
- [ ] **Step 3: Implement** fixtures, `mockDb`, `chatScript`, `handlers`, `browser.ts` (`setupWorker(...handlers)`), `server.ts` (`setupServer(...handlers)`), and the `main.tsx` switch.
- [ ] **Step 4: Run** `pnpm test src/mocks`; expect PASS. Then `pnpm dev` and check in the browser console that `[MSW] Mocking enabled` is logged.

---

### Task 4: i18n, theme, formatting

**Files:**

- Create: `web/src/i18n/en.json`, `web/src/i18n/vi.json`, `web/src/i18n/LanguageProvider.tsx`
- Create: `web/src/theme/theme.ts`
- Create: `web/src/format/money.ts`, `web/src/format/dates.ts`
- Test: `web/src/i18n/i18n.test.tsx`, `web/src/format/money.test.ts`, `web/src/format/dates.test.ts`

**Interfaces:**

- Produces in `LanguageProvider.tsx`: `LanguageProvider({ children })`, `useLanguage(): { lang: Language; setLang(lang: Language): void }`, `useT(): (key: MessageKey, vars?: Record<string, string | number>) => string` where `MessageKey = keyof typeof en` (flat dotted keys, `{name}` placeholders). Sets `document.documentElement.lang`. The json files hold every label used in Tasks 5 to 11, including the enum labels `group.<value>`, `style.<value>`, `mode.<value>`, `category.<value>`, `status.<value>`, and `errors.<code>` for `invalid_request`, `not_found`, `conflict`, `rate_limited`, `quota_exhausted`, `network_error`, `internal_error`, `payload_too_large`.
- Produces in `theme.ts`: `Theme = "light" | "dark"`, `initialTheme(): Theme` (stored choice, else `prefers-color-scheme`, else light), `applyTheme(theme: Theme): void` (toggles `.dark` on `<html>`, stores it; storage access wrapped in try/catch).
- Produces in `money.ts`: `formatMoney(amount: string | number, currency: string, lang: Language): string`, `toVnd(amount: string, rate: number): number` (display only, rounded to the nearest 1000 VND).
- Produces in `dates.ts`: `todayInVietnam(now?: Date): string` (`YYYY-MM-DD` via `Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Ho_Chi_Minh" })`), `tripDays(start: string, end: string): number` (both ends included), `formatDateRange(start: string, end: string, lang: Language): string`, `addDays(date: string, days: number): string`.

- [ ] **Step 1: Write the failing tests:**

```ts
it("vi_and_en_have_the_same_keys", () => {
  expect(Object.keys(vi).sort()).toEqual(Object.keys(en).sort());
});
it("use_t_switches_language_and_persists_it", async () => { ... });   // click toggle, text changes, localStorage tripPlanner.lang = "vi"
it("today_in_vietnam_is_next_day_at_1730_utc", () => {
  expect(todayInVietnam(new Date("2026-11-16T17:30:00Z"))).toBe("2026-11-17");
});
it("trip_days_counts_both_ends", () => { expect(tripDays("2026-12-20", "2026-12-23")).toBe(4); });
it("format_money_vnd_in_vi_has_dot_groups_and_no_decimals", () => {
  expect(formatMoney("1250000.00", "VND", "vi")).toBe("1.250.000 ₫");
});
it("format_money_thb_in_en_keeps_two_decimals", () => { expect(formatMoney("350", "THB", "en")).toBe("THB 350.00"); });
it("to_vnd_rounds_to_nearest_thousand", () => { expect(toVnd("350", 720.5)).toBe(252000); });
```

Note: `Intl` output uses a narrow no-break space in some locales; the tests normalise ` ` and ` ` to a plain space before comparing.

- [ ] **Step 2: Run** `pnpm test src/i18n src/format`; expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run**; expect PASS.

---

### Task 5: App shell, session, NamePage, routing

**Files:**

- Create: `web/src/session/session.ts`, `web/src/layout/AppShell.tsx`, `web/src/layout/AppShell.module.css`, `web/src/pages/NamePage.tsx`, `web/src/pages/NamePage.module.css`, `web/src/pages/NotFoundPage.tsx`
- Create: `web/src/test/renderApp.tsx`
- Modify: `web/src/App.tsx`
- Test: `web/src/pages/NamePage.test.tsx`, `web/src/layout/AppShell.test.tsx`

**Interfaces:**

- Produces in `session.ts`: `Session { userId: string; name: string }`, `readSession(): Session | null`, `saveSession(s: Session): void`, `clearSession(): void`, `useSession(): Session | null` (reads once per render from storage; `useSyncExternalStore` over a `storage` event so two tabs agree).
- Produces in `App.tsx`: routes `/start` NamePage, `/` HomePage, `/trips/new` NewTripPage, `/trips/:tripId` TripPage, `/chat` and `/chat/:conversationId` ChatPage, `*` NotFoundPage. Every route except `/start` and `*` redirects to `/start` when there is no session. One `QueryClient` with `retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2` and `refetchOnWindowFocus: false`.
- Produces in `AppShell.tsx`: `AppShell({ children, hasNav })`: the sticky 56px top bar from `docs/DESIGN.md` section 5 (logo, nav links My trips / New trip / Get ideas, EN/VI toggle, theme toggle, the visitor's name with a "Switch name" item that clears the session), and the content column. Below 640px the nav collapses into a menu button that opens a list. `hasNav` is false on NamePage.
- Produces in `renderApp.tsx`: `renderApp(path: string, opts?: { session?: Session | null; lang?: Language })` for page tests (providers + `MemoryRouter`).
- Pages pass placeholder components for routes not built yet; Tasks 6 to 11 replace them.

- [ ] **Step 1: Write the failing tests:**

```ts
it("redirects_to_start_without_a_session", async () => {
  renderApp("/", { session: null });
  expect(await screen.findByRole("heading", { name: /what should we call you/i })).toBeInTheDocument();
});
it("claiming_a_name_saves_the_session_and_opens_home", async () => { ... });  // types "Lan", submits, sees "My trips", localStorage has userId
it("blank_name_shows_inline_error_without_a_request", async () => { ... });
it("name_over_50_chars_is_blocked", async () => { ... });
it("language_toggle_switches_nav_labels_to_vietnamese", async () => { ... });
it("theme_toggle_adds_dark_class_to_html", async () => { ... });
it("unknown_path_shows_not_found_with_link_home", async () => { ... });
```

- [ ] **Step 2: Run** `pnpm test src/pages/NamePage src/layout`; expect FAIL.
- [ ] **Step 3: Implement** per `docs/DESIGN.md` sections 5 and 7 (NamePage is a 420px centred card, primary button, input recipe).
- [ ] **Step 4: Run**; expect PASS. Check both themes and both languages at 375px and 1280px in `pnpm dev`.

---

### Task 6: HomePage (trips, conversations, delete)

**Files:**

- Create: `web/src/api/users.ts`, `web/src/api/trips.ts`, `web/src/api/conversations.ts` (fetch functions + query hooks, extended in later tasks)
- Create: `web/src/pages/HomePage.tsx`, `web/src/pages/HomePage.module.css`, `web/src/components/ConfirmDialog.tsx`, `web/src/components/ConfirmDialog.module.css`, `web/src/components/EmptyState.tsx`
- Test: `web/src/pages/HomePage.test.tsx`

**Interfaces:**

- Produces in `trips.ts`: `tripKeys = { all: ["trips"], list: (userId) => [...], detail: (id) => [...] } as const`, `useUserTrips(userId: string)` (`GET /users/{id}/trips?limit=50`), `useDeleteTrip()` (mutation; on success removes the trip from the list cache).
- Produces in `conversations.ts`: `conversationKeys`, `useUserConversations(userId: string)`, `createConversation(body: { user_id: string; draft: RequestDraft | null }): Promise<Conversation>`.
- Produces: `ConfirmDialog({ isOpen, title, body, confirmLabel, onConfirm, onCancel })` over native `<dialog>` (`showModal()`), destructive confirm button, focus returns to the trigger on close. `EmptyState({ icon, text, action })` per the section 7 recipe.
- HomePage: trip cards (destination, date range, travelers, status badge, total or "Over budget" warning badge when `over_budget`), newest first, 3 / 2 / 1 columns; each card links to `/trips/{id}` and has a delete icon button (accessible name "Delete trip to {destination}"). Conversations list rows (title or first-message fallback "Untitled chat", updated date) link to `/chat/{id}`. Loading uses skeletons, an error shows the `errors.<code>` text with a Retry button.

- [ ] **Step 1: Write the failing tests:** `shows_seeded_trips_newest_first_with_status_badges`, `over_budget_trip_shows_warning_badge`, `empty_user_sees_empty_state_with_new_trip_button`, `delete_asks_for_confirmation_then_removes_the_card`, `cancel_delete_keeps_the_card`, `conversation_row_links_to_chat`, `list_error_shows_message_and_retry`.
- [ ] **Step 2: Run** `pnpm test src/pages/HomePage`; expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run**; expect PASS.

---

### Task 7: Trip form, place search, NewTripPage

**Files:**

- Create: `web/src/api/places.ts`, `web/src/components/PlaceSearch.tsx`, `web/src/components/PlaceSearch.module.css`
- Create: `web/src/components/TripForm.tsx`, `web/src/components/TripForm.module.css`, `web/src/components/validateTripForm.ts`
- Create: `web/src/pages/NewTripPage.tsx`
- Modify: `web/src/api/trips.ts` (add `useCreateTrip()`)
- Test: `web/src/components/validateTripForm.test.ts`, `web/src/components/TripForm.test.tsx`, `web/src/pages/NewTripPage.test.tsx`

**Interfaces:**

- Produces in `places.ts`: `usePlaceSearch(query: string)` (enabled at >= 2 trimmed chars, 300 ms debounce inside the component's state, `staleTime` 5 min).
- Produces: `PlaceSearch({ value: Place | null, onChange(place: Place | null) })`: combobox (`role="combobox"`, `aria-expanded`, `aria-activedescendant`, Up/Down/Enter/Escape), option rows "Đà Lạt" + "Lâm Đồng, Vietnam". Typing after a pick clears the value, so a free-text destination can never be submitted. Default suggestions under an empty input: the Vietnam entries of the search (Vietnam is the default country).
- Produces in `validateTripForm.ts`: `TripFormValues` (form state: `destination: Place | null`, strings for dates, numbers for travelers, `budget_amount: string`, arrays for styles and modes, ...), `validateTripForm(values: TripFormValues, today: string): Partial<Record<keyof TripFormValues, MessageKey>>` with the Global constraints rules; `toCreateTripBody(values, userId, conversationId, lang): CreateTripBody`; `fromDraft(draft: RequestDraft | null, place: Place | null): TripFormValues` (a `month` with no dates leaves dates empty; `length_days` with a start date fills the end date).
- Produces: `TripForm({ initialValues, onSubmit(values), isSubmitting, submitError: ApiError | null, onGetIdeas(values) })`. Fields: destination (PlaceSearch; the "Not sure where? Get ideas" link sits above it), origin (text, default empty), start and end date (`<input type="date">` with `min={todayInVietnam()}`), travelers (1 to 50), group type (select), travel styles (choice chips, at least one), transport modes (choice chips, optional, help text "Leave empty and we will compare 2 to 3 ways to get there"), budget (VND, digits only, grouped display) with per person / total radio, notes. For a destination outside VN show the hint "Prices will show in VND and {currency}" (currency from a small `COUNTRY_CURRENCY` map covering the `PLACES` countries; unknown -> no hint).
- NewTripPage: reads `?conversation=<id>` (loads that conversation's `request_draft`) and router state `{ place?: Place }`; submit calls `useCreateTrip` with `language` = UI language and navigates to `/trips/{id}`; "Get ideas" calls `createConversation({ user_id, draft })` and navigates to `/chat/{id}`. A 429 shows the `errors.quota_exhausted` or `errors.rate_limited` text above the submit button.

- [ ] **Step 1: Write the failing tests:**

```ts
it("rejects_start_date_before_today_in_vietnam", () => {
  expect(validateTripForm({ ...valid, start_date: "2026-11-16" }, "2026-11-17").start_date).toBe("form.errors.startInPast");
});
it("accepts_30_days_and_rejects_31", () => { ... });
it("requires_a_destination_from_search_and_one_style", () => { ... });
it("rejects_zero_budget_and_51_travelers", () => { ... });
it("to_create_trip_body_sends_empty_transport_modes_and_null_notes", () => { ... });
it("from_draft_fills_end_date_from_length_days", () => { ... });
```

and in `NewTripPage.test.tsx`: `typing_then_picking_a_place_and_submitting_opens_the_trip_page`, `typing_after_picking_clears_the_destination`, `prefills_from_conversation_draft_and_card_place`, `get_ideas_creates_conversation_with_current_values`, `quota_429_shows_try_again_tomorrow`, `abroad_destination_shows_two_currency_hint`.

- [ ] **Step 2: Run** `pnpm test src/components src/pages/NewTripPage`; expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run**; expect PASS.

---

### Task 8: TripPage status, polling, retry

**Files:**

- Create: `web/src/pages/TripPage.tsx`, `web/src/pages/TripPage.module.css`, `web/src/components/JobProgress.tsx`, `web/src/components/JobProgress.module.css`
- Modify: `web/src/api/trips.ts` (add `useTrip(id)`, `useRetryTrip()`)
- Test: `web/src/pages/TripPage.test.tsx`

**Interfaces:**

- Produces in `trips.ts`: `useTrip(tripId: string)` with `refetchInterval: (q) => ACTIVE.includes(q.state.data?.status) ? 2000 : false` where `ACTIVE = ["queued", "researching", "planning"] as const`; `useRetryTrip()` (on success invalidates the trip).
- Produces: `JobProgress({ status: TripStatus, failureReason: string | null, onRetry(): void, isRetrying: boolean })`: three steps per the section 7 recipe; `failed` shows the reason text (`trip.failure.<reason>`, with `quota_exhausted` using the pinned quota copy) and a Retry button.
- TripPage layout per `docs/DESIGN.md` section 5: plan pane (Task 9 fills it) and chat panel slot (Task 11 fills it). `plan === null` and active: progress card only, chat slot disabled. `plan !== null` and active (re-plan): progress card above the plan, plan and export stay usable. `failed` with a plan: failure card above the plan. 404: "Trip not found" with a link home.

- [ ] **Step 1: Write the failing tests** (fake timers + `mockDb.setNow`):

```ts
it("polls_every_2s_until_ready_then_stops", async () => {
  // count GET /trips/{id} requests through an MSW listener; after ready, advance 10 s, count unchanged
});
it("shows_researching_then_planning_steps", async () => { ... });
it("failed_trip_shows_reason_and_retry_restarts_progress", async () => { ... });
it("quota_failed_trip_shows_try_again_tomorrow", async () => { ... });
it("replan_keeps_plan_visible_with_progress_card_above_it", async () => { ... });
it("unmount_during_polling_makes_no_more_requests", async () => { ... });
it("unknown_trip_shows_not_found", async () => { ... });
```

- [ ] **Step 2: Run** `pnpm test src/pages/TripPage`; expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run**; expect PASS.

---

### Task 9: PlanView, transport options, export

**Files:**

- Create: `web/src/components/PlanView.tsx`, `web/src/components/PlanView.module.css`, `web/src/components/Price.tsx`, `web/src/components/Price.module.css`, `web/src/components/TransportOptions.tsx`, `web/src/components/TransportOptions.module.css`, `web/src/components/ExportButton.tsx`, `web/src/components/categoryIcon.ts`
- Modify: `web/src/pages/TripPage.tsx` (render `PlanView` when `plan` is set)
- Test: `web/src/components/PlanView.test.tsx`, `web/src/components/Price.test.tsx`

**Interfaces:**

- Produces: `Price({ amount: string; currency: string; basis: PriceBasis; sourceUrl: string | null; currencies: Plan["currencies"] })`: tabular amount; `source` with a URL renders the amount as an external link (`target="_blank" rel="noopener noreferrer"`); `source` without a URL, or `estimate`, renders the amount plus the "Estimate" badge (no link is ever invented); a local-currency price on a trip abroad adds the `≈ <VND>` line from `toVnd`.
- Source URLs come from `trip.sources[String(item.source_id)]` (contract section); the mock fills it from `SOURCES`.
- Produces: `categoryIcon(category: Category, mode: TransportMode | null): LucideIcon` mapping from `docs/DESIGN.md` section 7.
- Produces: `PlanView({ trip: Trip & { plan: Plan } })` sections in this order: header (plan title, summary, destination, date range, travelers, budget vs `total_cost_vnd`, rate line "1 THB = 720.5 VND (2026-11-16)" for trips abroad), warnings (each `plan.warnings` entry; `over_budget` states the amount `total_cost_vnd - budget total`), days (one day card per `plan.days`: date, theme, weather chip with min-max °C and mm, "Typical" badge plus tooltip "Based on the same dates last year" when `basis === "typical"`; item rows: time in mono, category icon, title, location, `Price`, status badge for `booked` / `paid`, note), TransportOptions, accommodation (chosen first, nights x rooms, `Price`), checklist (read-only list with prices; ticking is done through chat).
- Produces: `TransportOptions({ options: TransportOption[]; currencies; sources })`: grouped by leg (`outbound`, `return`, `local`), each option card with mode icon, summary, depart time, duration as `Xh Ym`, `Price`, pros and cons; chosen card per the recipe with a "Chosen" badge; a line "Ask in the chat to switch" under each leg.
- Produces: `ExportButton({ tripId: string; isDisabled: boolean })`: an `<a href={apiUrl(`/trips/${id}/export.xlsx`)} download>` styled as a secondary button; disabled (rendered as a disabled `<button>`) while `plan` is null.

- [ ] **Step 1: Write the failing tests:**

```ts
it("estimate_price_shows_badge_and_no_link", () => { ... });
it("source_price_without_url_falls_back_to_estimate_badge", () => { ... });
it("local_price_on_abroad_trip_shows_vnd_line", () => {
  render(<Price amount="350" currency="THB" basis="source" sourceUrl="https://x.test" currencies={ABROAD} />);
  expect(screen.getByRole("link", { name: /THB 350/ })).toHaveAttribute("href", "https://x.test");
  expect(screen.getByText(/≈ ₫252,000/)).toBeInTheDocument();   // en-US formatting
});
it("renders_one_card_per_day_with_items_in_time_order", () => { ... });
it("typical_weather_day_shows_typical_badge", () => { ... });
it("over_budget_warning_states_the_amount", () => { ... });
it("domestic_trip_has_no_rate_line", () => { ... });
it("transport_options_group_by_leg_and_mark_the_chosen_one", () => { ... });
it("export_link_points_at_export_route_when_plan_exists", () => { ... });
```

- [ ] **Step 2: Run** `pnpm test src/components/PlanView src/components/Price`; expect FAIL.
- [ ] **Step 3: Implement** to the section 7 recipes (day card, item row 56px min, price, badge, weather chip, warning banner, transport option card).
- [ ] **Step 4: Run**; expect PASS. Check a 30-day mock trip scrolls without layout breaks and that long Vietnamese titles wrap.

---

### Task 10: Chat streaming, ChatPanel, suggestion cards

**Files:**

- Create: `web/src/chat/useChatStream.ts`, `web/src/components/ChatPanel.tsx`, `web/src/components/ChatPanel.module.css`, `web/src/components/SuggestionCard.tsx`, `web/src/components/SuggestionCard.module.css`
- Modify: `web/src/api/conversations.ts` (add `useConversation(id)`, `sendMessage(...)`)
- Test: `web/src/chat/useChatStream.test.tsx`, `web/src/components/ChatPanel.test.tsx`

**Interfaces:**

- Produces in `conversations.ts`: `sendMessage(conversationId: string, body: { content: string; trip_id: string | null; plan_revision: number | null }, signal: AbortSignal): Promise<ReadableStream<Uint8Array>>` (throws `ApiError` for a JSON error response), `useConversation(conversationId: string)`.
- Produces in `useChatStream.ts` (shared by ChatPage and TripPage, so a hook is justified): `useChatStream(conversationId: string | null, opts: { tripId: string | null; planRevision: number | null; ensureConversation(): Promise<string> })` returning `{ state: ChatState; send(content: string): Promise<void>; abort(): void }` where `ChatState` is a union: `{ kind: "idle" } | { kind: "streaming"; text: string } | { kind: "error"; code: string; draft: string }`. On `plan` it invalidates `tripKeys.detail(tripId)`; on `suggestions` it keeps the cards on the streamed assistant message; on `done` it invalidates the conversation so the saved messages replace the local stream; a `409` invalidates the trip and sets `error` with `code: "conflict"` and the unsent text as `draft`; `quota_exhausted` sets `error`. Aborts on unmount.
- Produces: `ChatPanel({ conversationId: string | null; tripId: string | null; planRevision: number | null; isDisabled: boolean; disabledReason: MessageKey | null })`: thread (assistant text plain, visitor bubble right, "Plan updated" line after a plan change, suggestion cards inside the assistant message), composer (`<textarea>` 1 to 4000 chars, Enter sends, Shift+Enter newline, send icon button with accessible name "Send"), conflict notice "This plan changed, here is the latest version" with the draft kept in the composer, quota notice disables the composer, the panel scrolls to the newest message unless the visitor scrolled up. An empty thread on a trip shows three example prompts as ghost buttons ("Is the weather OK for day 2?", "Find a cheaper hotel", "Switch to the train"), each sending its text.
- Produces: `SuggestionCard({ card: SuggestionCard; onPlan(card): void })`: name and flag-free country name, why, days, cost per person `Price` with basis `estimate`, best months, highlights, "Plan this trip". `onPlan` (in ChatPanel): `GET /places?q=<card.name>`, pick the first result with the same `country_code`, navigate to `/trips/new?conversation=<id>` with state `{ place }`; no match -> navigate without a place and the form shows "Pick the destination from the search".

- [ ] **Step 1: Write the failing tests:**

```ts
it("streams_tokens_into_one_assistant_message", async () => { ... });  // text grows, then saved message replaces it
it("edit_reply_invalidates_trip_and_shows_plan_updated", async () => { ... });
it("conflict_409_reloads_trip_shows_notice_and_keeps_draft", async () => {
  mockDb.bumpRevision(TRIP_ID);  // another tab saved first
  await user.type(composer(), "Switch to the train{Enter}");
  expect(await screen.findByText(/this plan changed/i)).toBeInTheDocument();
  expect(composer()).toHaveValue("Switch to the train");
});
it("quota_exhausted_disables_composer_with_try_again_tomorrow", async () => { ... });
it("suggestion_card_plan_this_trip_opens_prefilled_form", async () => { ... });
it("unmount_mid_stream_aborts_the_request", async () => { ... });
it("message_over_4000_chars_cannot_be_sent", async () => { ... });
```

- [ ] **Step 2: Run** `pnpm test src/chat src/components/ChatPanel`; expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run**; expect PASS.

---

### Task 11: ChatPage and the trip chat panel

**Files:**

- Create: `web/src/pages/ChatPage.tsx`, `web/src/pages/ChatPage.module.css`
- Modify: `web/src/pages/TripPage.tsx`, `web/src/pages/TripPage.module.css`
- Test: `web/src/pages/ChatPage.test.tsx`, extend `web/src/pages/TripPage.test.tsx`

**Interfaces:**

- ChatPage: `/chat/:conversationId` loads the conversation and renders `ChatPanel` in the reading column with its title; `/chat` (from "Get ideas" in the nav) shows the empty thread with the discovery prompt "Tell me roughly when, with whom and your budget" and creates the conversation on first send (`ensureConversation`), then replaces the URL with `/chat/{id}`. A "New chat" ghost button in the page header.
- TripPage chat: the conversation is `trip.conversation_id` if set, else the visitor's most recent conversation from `useUserConversations`, else created on first send. It sends `trip_id` and the trip's `plan_revision`. `isDisabled` only while `plan === null` (first generation), with reason "The chat opens when the plan is ready"; during a re-plan the chat stays open. Note: `docs/DESIGN.md` section 5 says the panel is disabled while the trip is active; this task follows the spec (questions are answered during a re-plan), and the guide row is updated to "disabled while the first plan is being made".
- Layout: >= 1024px the 400px panel sits beside the plan with its own scroll; below 1024px a 48px "Ask about this plan" button fixed bottom right opens the panel as a native `<dialog>` bottom sheet (85vh, `translateY(100%)` enter 250ms per section 6), Escape and the close button dismiss it, focus returns to the button.

- [ ] **Step 1: Write the failing tests:** `chat_route_without_id_creates_conversation_on_first_send_and_updates_url`, `discovery_reply_shows_three_suggestion_cards`, `trip_chat_sends_trip_id_and_plan_revision` (assert on the request body seen by MSW), `trip_chat_is_disabled_until_first_plan_is_ready`, `trip_chat_stays_open_during_replan`, `small_screen_opens_chat_sheet_from_button` (set `window.matchMedia` to `(max-width: 1023px)`).
- [ ] **Step 2: Run** `pnpm test src/pages`; expect FAIL.
- [ ] **Step 3: Implement**, and edit the TripPage row of `docs/DESIGN.md` section 5 as stated above.
- [ ] **Step 4: Run**; expect PASS.

---

### Task 12: Run it together, verify

**Files:**

- Create: `web/Dockerfile` (node 24 alpine, `corepack enable`, `pnpm install --frozen-lockfile`, `pnpm dev --host 0.0.0.0`)
- Modify: `docker-compose.yml` (add service `web`: build `./web`, port `5173:5173`, `env_file: web/.env` if present, environment `VITE_API_MOCK=${VITE_API_MOCK:-true}`, `VITE_API_BASE_URL=http://localhost:8000`). This is build config: confirm with the user before applying.
- Modify: `CLAUDE.md` (Commands: the `web/` commands; Project state: frontend built against mocks)

**Interfaces:**

- Switching to the real backend later: set `VITE_API_MOCK=false`; nothing else changes. Any field-name mismatch is fixed in `web/src/api/api.types.ts` and `web/src/mocks/fixtures.ts`.

- [ ] **Step 1: Run the checks** in `web/`: `pnpm lint && pnpm typecheck && pnpm test && pnpm build`. Expected: no Biome errors, no type errors, all tests pass, `dist/` built.
- [ ] **Step 2: Run the design checks:** `node ../.claude/skills/ui-planning/scripts/contrast-check.mjs src/styles/tokens.css --pair warning-foreground:warning` -> 0 failing; `grep -rnE "#[0-9a-fA-F]{3,8}\b|rgba?\(" src --include=*.tsx --include=*.module.css` -> no output; `grep -n "/\*" src/styles/tokens.css` -> no output.
- [ ] **Step 3: Manual walkthrough** in `pnpm dev` (mock on), in EN and VI, light and dark, at 375px and 1280px: claim a name, create a domestic trip and watch it reach ready, open the abroad trip (two currencies, rate line, over-budget warning), ask a question and an edit in the chat, change the dates in chat and see the re-plan, get ideas from the nav and plan a suggested destination, export, delete a trip. Report anything that does not match `docs/DESIGN.md` to the user.
- [ ] **Step 4: Run** `docker compose up web` and open `http://localhost:5173`; expect the same app.
