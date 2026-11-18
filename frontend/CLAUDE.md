# UI design guide - AI Trip Planner

**This file is the design guide for this project. Read it fully before writing or changing any UI.**

- Tokens live in `frontend/index.css`, the app's only stylesheet: the tokens, then `@theme inline` mapping them to Tailwind utilities. Never retype the values, never add a hex to a component.
- Everything below is decided. This document is not a starting point to improve on; the direction was chosen from four alternatives that are still on record in `docs/design/ui-options.html`.
- If something you need is not covered here, pick the smallest choice consistent with section 1, build it, and say in the chat what you decided so it can be added.
- Direction changes edit this file in place. There is never a second version of it.
- `frontend/ui-component-principles.md` holds the reusable minimum requirements for the components it covers (now the conversation sidebar and the chat input). A change to the behaviour, structure, states or API of one of those components updates that file in the same change, so the two never disagree. A component added to it follows the same rule from then on.

Direction picked 2026-11-16 · Stack: React + TypeScript on Vite, styled with Tailwind CSS v4 (`frontend/`). The only stylesheet is `frontend/index.css`; components style themselves with Tailwind utility classes, and the shared recipes of section 7 live as class strings in `frontend/src/styles/recipes.ts`.

## 1 Direction

**Lagoon** - a calm sea-teal travel assistant: white cards lifted off a cool page, the plan reads like a travel app, not a spreadsheet.

- **Axis:** calm consumer travel app, elevated cards on a cool tinted page.
- **Commits to:** one accent (teal `--primary`) used for actions, links and the selected state only; plan content (times, prices, weather) is readable at a glance in both EN and VI; every price shows its basis (source link or "Estimate").
- **Gave up:** a strong brand personality. The look is quiet on purpose, so the destination content and the plan carry the page.
- **Brand colour:** `#0F6E69`, proposed by this direction (no brand colour was supplied).
- **Reference sites the user named:** none.

Extending this direction to something not covered below means asking "which choice keeps the axis and the commitments true?" - not "what looks good here?".

## 2 Tokens

Full values, both modes, live in `frontend/index.css` - do not retype them. Ported from `docs/design/option-tokens/A-lagoon.css`.

| Token | Role |
|---|---|
| `--background` | page |
| `--foreground` | body text |
| `--card` | raised container fill |
| `--card-foreground` | text on card |
| `--primary` | primary action, links, selected state |
| `--primary-foreground` | text on primary |
| `--secondary` | secondary action, visitor chat bubble |
| `--muted` | quiet fill, skeletons |
| `--muted-foreground` | secondary text, VND conversion line |
| `--accent` | hover tint, active nav item |
| `--destructive` | delete, failed job, form error |
| `--warning` | over budget, estimate badge, typical weather, quota message |
| `--warning-foreground` | text on warning |
| `--border` | hairlines, dividers |
| `--input` | form control border |
| `--ring` | focus indicator |

Radius: `--radius: 0.75rem` (12px). Corners derive from it: controls `calc(var(--radius) - 4px)` (8px), cards `var(--radius)`, sheets and modals `calc(var(--radius) + 4px)`, chips and badges `999px`. No other literal `border-radius` in a component.

Surface kit variables (`--surface-*`, both modes) live in `frontend/index.css`.

Rules that hold everywhere:

- Every colour, radius and shadow in a component is a Tailwind utility generated from a token: `bg-card`, `text-muted-foreground`, `border-border`, `rounded-sm` / `rounded-md` / `rounded-lg`, `shadow-surface` / `shadow-raised`. A literal hex, `rgb()` or arbitrary colour (`bg-[#...]`) ignores the mode toggle and drifts on the first theme edit.
- Spacing uses Tailwind's 4px scale, which matches `--space-*` one to one (`p-4` = `--space-4` = 16px). Layout sizes read the shell tokens: `max-w-(--shell-reading)`, `h-(--shell-topbar)`.
- No component adds a CSS file or a `style` attribute for a static value.
- Both modes ship together. A component is not done until it has been looked at in dark.
- Dark mode is the `.dark` class on `<html>`. Default follows `prefers-color-scheme`; an explicit choice from the theme toggle at the bottom of the sidebar is kept in `localStorage` (same pattern as the UI language). Default with no signal: **light**.

## 3 Fonts

| Role | Family | Token | Loaded via |
|---|---|---|---|
| Display / headings | Be Vietnam Pro 600, 700 | `--font-sans` | Google Fonts, `vietnamese` and `latin` subsets |
| Body | Be Vietnam Pro 400, 500 | `--font-sans` | Google Fonts, same request |
| Mono / numerals | JetBrains Mono 400, 500 | `--font-mono` | Google Fonts; used only for times and the trip id |

Type scale (px / line height): page title 28/36 700 (`text-title`) · section title 20/28 600 (`text-xl`) · card title 16/24 600 (`text-base`) · body 16/24 400 · small 14/20 (`text-sm`) · caption and badge 12/16 500 (`text-xs`). Headings use `tracking-tight`; body stays at 0. `TITLE.page` / `TITLE.section` / `TITLE.card` in `recipes.ts` hold the heading classes.

Prices, totals, dates and temperatures use `tabular-nums` in `--font-sans` so columns line up; times (`08:00 - 09:30`) use `font-mono`. No component names a family directly: `--font-sans` and `--font-mono` in `frontend/index.css` override Tailwind's defaults, so `font-sans` / `font-mono` read them.

## 4 Surface kit

**`elevated`** - 1px hairline in `--border` plus a soft diffuse shadow, no blur, no gradient.

A container in this project is: `--card` fill, 1px `--border`, `--surface-shadow`, radius `--radius`, on the `--background` page. In code that is `SURFACE` (no padding, for a container whose content sets its own) or `CARD` (`SURFACE` + `p-5`) from `recipes.ts`; never add padding classes on top of `CARD` to cancel it.

- Components use `shadow-surface` / `shadow-raised` rather than inventing their own.
- Raised things (popovers, place-search dropdown, the account menu, the mobile chat sheet, the sidebar drawer, modals, toasts) use `shadow-raised`; nothing else does.
- Nested containers do not stack shadows: an item row inside a day card is a `--border` divider, not a second card.

## 5 Layout & density

### The app shell

Every signed-in screen sits inside this skeleton. A new screen extends it; it does not invent its own.

```
┌──────────────┬───────────────────────────────────────────┐
│ sidebar      │ main area                                 │
│ 288px        │ content column, max 1120px, centred,      │
│ logo         │ padding --space-8 (--space-4 below 640px) │
│ [Get ideas]  │ reading pages (form, plan): max 720px     │
│ My trips     │                                           │
│ ──────────── │                                           │
│ Conversations│                                           │
│  row         │                                           │
│  row (own    │                                           │
│  scroll)     │                                           │
│ ──────────── │                                           │
│ name EN/VI ◐ │                                           │
└──────────────┴───────────────────────────────────────────┘

TripPage at ≥1280px (main area only):
┌────────────────────────────────────┬─────────────────────┐
│ plan pane (fills, reading max 720) │ chat panel 480px    │
│ header, warnings, days, transport, │ thread + composer,  │
│ stay, checklist                    │ sticky, own scroll  │
└────────────────────────────────────┴─────────────────────┘

ChatPage (main area only, edge to edge, no padding, no card):
┌──────────────────────────────────────────────────────────┐
│ header: conversation title (section title), no rule      │
├──────────────────────────────────────────────────────────┤
│ thread, full width, own scroll                           │
├──────────────────────────────────────────────────────────┤
│ composer pill, no rule above                             │
└──────────────────────────────────────────────────────────┘
```

| Region | Size | Fill / edge |
|---|---|---|
| Sidebar | 288px (`w-72`), full viewport height, sticky; below 1024px a drawer opened from a menu button, over a `--foreground` 40% backdrop | `--card`, `--border` right edge |
| Mobile top bar (<1024px) | `--shell-topbar` (56px), sticky: menu button + logo | `--background`, `--border` bottom edge, no shadow |
| Main area | right of the sidebar; content column max `--shell-content` (1120px), centred, padding `--space-8` (`--space-6` from 640px, `--space-4` below) | `--background` |
| Reading column | max `--shell-reading` (720px) | form, plan pane |
| Trip chat panel (≥1280px) | `--shell-chat-panel` (480px), sticky, full height; on TripPage the main area widens to `--shell-trip` (reading column + panel + gap) from 1280px | `--card`, surface kit |
| Mobile chat sheet (<1280px) | 85vh bottom sheet, opened by a 48px "Ask about this plan" button fixed bottom-right | `--card`, `--surface-shadow-raised`, top radius `calc(var(--radius) + 4px)` |
| Signed-out top bar (NamePage, unknown path) | 56px: logo + EN/VI + theme, no sidebar | `--background`, `--border` bottom edge |

Sidebar, top to bottom:

- Logo, links to `/`.
- **Get ideas**: the one primary button, full width, links to `/chat` and always starts an empty chat. There is no separate "New chat" or "New trip" button in the sidebar; a trip is started from the "New trip" button on HomePage or from a suggestion card.
- **My trips**: a nav row, `--accent` fill when active.
- **Conversations**: a 12px `--muted-foreground` label, then the visitor's conversations newest first, each a row with no icon: the title (16px 500) on one line, truncated with an ellipsis, min 44px; the open one has `--accent` fill. On hover (always on touch screens) a 36px `ellipsis-vertical` icon button at the right of the row (hovering it, or having its menu open, keeps the whole row in its `--accent` hover fill) opens a raised menu (padding `--space-1`, 32px items) to the right of the button with top edges aligned (4px gap), flipping to the button's left when the viewport has no room on the right. The menu starts with the update time "HH:MM DD/MM/YYYY" (12px `--muted-foreground`, Vietnam time) above a `--border` rule, then Rename (opens the confirm dialog with a "Conversation name" field prefilled and selected; Enter or "Save name", a primary button, saves; empty disables saving) and Delete (in `--destructive`, asks through the confirm dialog). Only this list scrolls. No tabs.
- Footer, above a `--border` rule: the name (opens a small menu with "Switch name"), the EN/VI toggle and the theme toggle.

| Page (`frontend/src/pages/`) | Layout inside the main area |
|---|---|
| NamePage | single card, max 420px, centred vertically; signed-out top bar |
| HomePage | "My trips" title with a "New trip" primary button (it opens the trip form in a modal, `NewTripDialog`: reading-column wide, max viewport height minus 32px, its own scroll, a sticky header with the "Plan a new trip" section title and a close icon button; Escape closes it and the form starts fresh on every open), then a grid of trip cards (3 columns ≥1280, 2 ≥640, 1 below). Conversations are not repeated here; they live in the sidebar |
| NewTripPage | reading column with the TripForm card, opened from a suggestion card or a chat draft; "Starting from" defaults to Hà Nội when the draft has no origin; the "Not sure where? Get ideas" link sits above the destination field |
| ChatPage | fills the whole main area edge to edge, as sketched: no outer padding, no card around the thread, no "New chat" button. Suggestion cards stack 1 per row in the thread |
| TripPage | plan pane and chat panel as sketched; while `queued` / `researching` / `planning` the plan pane shows the progress card; the chat panel is disabled while the first plan is being made, and stays open during a re-plan, when the progress card sits above the current plan |

- **Where a new component goes by default:** inside the plan pane or reading column, full width, stacked with `--space-6` between sections - never a new panel beside the chat panel.
- **What a new screen must reuse:** the sidebar and main area are fixed; a screen owns only what is inside the main area.
- **Nav pattern:** the sidebar is the only navigation. A new destination is one more nav row under My trips, never a second nav bar, a tab strip, or a second primary button.

### Density and spacing

- **Density: 5** - item rows min 56px tall, card padding `--space-5`, form fields 44px tall, chat bubbles padding `--space-3` / `--space-4`.
- **Spacing scale:** `--space-1` to `--space-12` in `frontend/index.css` (4, 8, 12, 16, 20, 24, 32, 48 px). Section gaps `--space-6`, inside a card `--space-4`, between form fields `--space-4`, between a label and its field `--space-2`.
- **Breakpoints:** Tailwind's `sm` 640px (phone to tablet), `lg` 1024px (sidebar fixed instead of a drawer), `xl` 1280px (trip chat panel beside the plan instead of a sheet).
- **Conventions preserved from the existing app:** none, this is new.
- Below 640px a price that sits right of a title (plan item, transport option, stay, checklist) moves under the title, left-aligned with it, so the title keeps the full row width.
- Body text stays under ~70 characters per line; Vietnamese strings run about 20% longer than English, so buttons never get a fixed width.

## 6 Motion

- **Frequency decides whether to animate at all.** Sending a chat message, typing, switching day tabs and toggling a checklist item get **none**. Occasional UI (place-search dropdown, account menu, sidebar drawer, mobile chat sheet, toasts, modals) may.
- **Durations:** press feedback 120ms · tooltips and dropdowns 150-200ms · sheet, drawer and modal 250ms. Nothing in UI over 300ms. The animations are tokens in `frontend/index.css`: `animate-pop-in` (dropdowns, menus), `animate-dialog-in`, `animate-sheet-in`, `animate-drawer-in`, `animate-breathe` (progress pulse).
- **Easing:** `cubic-bezier(0.2, 0, 0, 1)` (`ease-standard`) on enter and feedback; exit at 70% of enter. Never `ease-in`.
- **Animate `transform`, `opacity` and colour only.** `transition duration-120 ease-standard`, never `transition-all`.
- **Press:** `active:scale-[0.97]` on buttons (`active:scale-[0.99]` on clickable cards), without reflowing a sibling.
- **Enter from `scale(0.95)`** with opacity 0, never `scale(0)`. The sheet enters with `translateY(100%)`, the sidebar drawer with `translateX(-100%)`.
- Streaming chat text appears as it arrives with no per-token fade. The job progress card pulses its current step with an opacity 0.6 to 1 loop at 1.2s, off under `prefers-reduced-motion: reduce`.
- Hover feedback is colour, opacity, or border. Tailwind v4's `hover:` already applies only on devices that can hover.

## 7 Component recipes

Written in tokens and states. The shared ones (button, card, badge, banner, field, input, empty state, skeleton, titles) exist as Tailwind class strings in `frontend/src/styles/recipes.ts`; use those constants instead of retyping the classes. Anything not here follows section 1.

| Component | Fill | Border / radius | Size | States |
|---|---|---|---|---|
| Button, primary | `--primary`, text `--primary-foreground` | none, 8px | height 44px, padding 0 `--space-5`, 16/24 600 | hover opacity 0.9 · active `scale(0.97)` · focus-visible 2px `--ring` at 2px offset · disabled opacity 0.5, no pointer |
| Button, secondary | `--secondary`, text `--secondary-foreground` | none, 8px | as primary | hover `--accent` fill · rest as primary |
| Button, ghost | transparent, text `--foreground` | none, 8px | height 36px, padding 0 `--space-3` | hover `--accent` fill |
| Button, destructive | `--destructive`, text `--destructive-foreground` | none, 8px | as primary | used only inside the delete confirms (trip, conversation) |
| Card / panel | `--card`, text `--card-foreground` | per section 4, `--radius` | padding `--space-5` | clickable trip card: hover border `--input`, active `scale(0.99)` |
| Input, select, date | `--card` | 1px `--input`, 8px | height 44px, padding 0 `--space-3` | focus ring · error 1px `--destructive` border + 14px message in `--destructive` below · disabled `--muted` fill |
| Place search | input as above + dropdown | dropdown `--popover`, `--surface-shadow-raised`, `--radius` | max 10 rows, 48px each: place name 16px, country 14px `--muted-foreground` | highlighted row `--accent` · empty "No places found" in `--muted-foreground` |
| Choice chip (travel style) | off: `--card`, 1px `--input` · on: `--accent`, 1px `--primary`, text `--accent-foreground` | 999px | height 36px, padding 0 `--space-4` | on adds a 16px check icon before the label · below the travel style chips a 14px `--muted-foreground` line (min two lines tall) shows the hovered or focused style as "**Name:** description" (the name in `--foreground` 500), and a prompt before any is touched; each checkbox carries its description as `aria-describedby`. The trip request has no transport, group or conversation field: the backend picks the transport options, and the trip is not linked to a conversation |
| Day card | card | per section 4 | header row: date (section title) + weather chip; item rows below with `--border` dividers | - |
| Plan item row | none (inside day card) | top 1px `--border` | min 56px; time in `--font-mono` 14px `--muted-foreground` · 20px category icon · title 16px 500 · price right-aligned | `status` booked / paid as a badge after the title |
| Price | text `--foreground`, tabular | - | abroad: local amount first, VND below in 14px `--muted-foreground` (`≈ 1.250.000 ₫`) | source: price is a `--primary` link with a 14px external icon · estimate: price + "Estimate" badge |
| Badge | estimate and typical weather: `--warning` / `--warning-foreground` · booked: `--secondary` · paid: `--accent` | 999px | height 22px, padding 0 `--space-2`, 12/16 500 | - |
| Weather chip | `--muted`, text `--foreground` | 999px | icon + "14-23 °C · 2 mm"; "Typical" badge when `basis` is `typical` | - |
| Warning banner (over budget, quota) | `--warning`, text `--warning-foreground` | 1px `--warning-foreground` at 30% opacity, `--radius` | padding `--space-4`, 20px alert icon; over budget states the amount ("Over budget by 2.400.000 ₫") | quota banner carries the reset time |
| Transport option card | card; chosen: 2px `--primary` border | `--radius` | mode icon + summary, duration, price, pros/cons as two short lists | chosen shows a "Chosen" `--primary` badge; switching is done from chat |
| Job progress card | card | per section 4 | 3 steps (queued, researching, planning) as a row of dots + labels | current step `--primary` + pulse · done check `--primary` · failed: `--destructive` text + Retry primary button |
| Sidebar row (nav, conversation) | none; active or hover `--accent`, text `--accent-foreground` when active | 8px | nav min 36px, conversation min 44px, padding `--space-2` `--space-3` | - |
| Chat bubble | assistant: none, text `--foreground` on the panel · visitor: `--secondary`, text `--secondary-foreground`, right-aligned | 12px, the corner nearest the sender 4px | max 85% of thread width, padding `--space-3` `--space-4` | plan-change result shows a 14px "Plan updated" line in `--primary` below the reply |
| Chat composer | pill `--muted`, no border, no shadow; it floats over the thread (sticky at the bottom of the thread's scroll area) with a transparent surround, so messages scroll behind it and fade out (a `from-transparent` to page-fill gradient, 24px above the pill down to the strip); the disclaimer strip below it has the page fill (`--background` on ChatPage, `--card` in the trip chat panel). On ChatPage the pill is 50% of the main area wide from 640px, centred; full width in the trip panel and on phones | `999px` pill on one line; once the text wraps, `calc(var(--radius) + 4px)` with the text on top and the buttons in a row below, until the text is cleared | single line: `plus` (attach), textarea, ghost model picker ("Auto" + `chevron-down`, hidden while the composer is under 448px wide, a container query on the pill wrapper), `mic`, send (40px round `--primary`, 20px `arrow-up`, `BUTTON.iconPrimary`). Wrapped: textarea (grows to 200px) with a `maximize-2` / `minimize-2` toggle at its top right that grows it to 40-60dvh, then `plus` left and model, mic, send right. Attach, model and mic are `aria-disabled` with a "Coming soon" tooltip until the backend supports them. Disclaimer 12px `--muted-foreground`, centred | focus-within: 3px `--ring` 30% halo, painted above the disclaimer strip · disabled 60% opacity, with the quota message when `quota_exhausted` |
| Chat welcome panel | none | - | shown while the thread is empty and the chat is enabled, centred in the thread, enters with `animate-pop-in`: 56px `--accent` circle with a 28px `sparkles` icon and an 8px `--accent` 40% halo, title (page title on ChatPage, section title in the trip panel), one 16px `--muted-foreground` line, then example prompts as cards that send on click: `--card`, 1px `--border`, `--radius`, padding `--space-3`, a 36px `--muted` circle with a 20px topic icon (`cloud-sun`, `bed-double`, `train-front` in a trip; `waves`, `users`, `plane` in discovery), the prompt in 14px, and a 16px `arrow-up-right` shown on hover; 3 columns from 640px on ChatPage (max 768px), 1 column in the trip panel | card hover: `--input` border, `--accent` fill, icon circle turns `--card` with a `--primary` icon · active `scale(0.99)` |
| Suggestion card | card | per section 4 | place + country, "why it fits", days, cost per person + "Estimate" badge, best months, "Plan this trip" primary button | - |
| Empty state | none | - | 48px icon in `--muted-foreground`, one 16px line, one primary button | - |
| Skeleton | `--muted` | `--radius` | matches the block it replaces | no shimmer; static fill |

- **Focus is visible on every interactive element** - 2px `--ring` at 2px offset (set once in the base layer of `frontend/index.css`).
- Icons from Lucide only, 20px in rows and buttons, 16px inside chips and badges, 1.75px stroke. Category icons: transport `bus` / `plane` / `train-front` / `car` by mode, accommodation `bed-double`, food `utensils`, shopping `shopping-bag`, service `ticket`, sightseeing `camera`. Never emoji as an icon.
- Money is formatted with `Intl.NumberFormat` in the UI locale (`en` or `vi`) and the price's own currency; code never converts a `source` price for display except the `≈` VND line.
- **Tailwind wiring:** the custom properties in `frontend/index.css` are registered with Tailwind v4 in its `@theme inline` block (colours, radius, shadows, motion); a new token needs a line there before a utility can use it.

## 8 Do not

- Do not add a colour that is not a token. Trip categories are told apart by icon, not by colour; there are no chart or category colours in this palette.
- Do not use `--primary` for decoration (headers, backgrounds, illustrations). It marks actions, links, the chosen option and the current step.
- Do not use `--destructive` for over budget or typical weather; those are `--warning`. Red is for delete, failure and form errors.
- Do not show a price without its basis, and do not render a source link the plan does not have.
- Do not hardcode a radius, a shadow, or a font family (`rounded-[...]`, `shadow-[...]`, `font-[...]`) - `rounded-sm/md/lg`, `shadow-surface/raised` and `font-sans/mono` exist for it. The one exception is the 4px sender corner of a chat bubble.
- Do not stack a shadowed card inside a shadowed card.
- Do not add a second nav, a top-bar nav on wide screens, or tabs in the sidebar. The sidebar is the only navigation; the trip chat panel is the only other side region and exists only on TripPage.
- Do not add a CSS file, a CSS module or a `<style>` block; new tokens go in `frontend/index.css` with a matching `@theme inline` line, everything else is a utility class.
- Do not set fixed widths on text containers; Vietnamese labels must fit.
- Do not hardcode UI text in components; every string comes from `en.json` / `vi.json`.
- Do not write comments in `frontend/index.css`.
- Do not ship a component that only works in light mode.
- Do not animate a high-frequency or keyboard-triggered action, use `transition: all`, `ease-in`, or a `scale(0)` entrance.
- Do not introduce a second UI library, icon set, or type scale.
- Do not use pure `#000` as text or `#fff` as a dark-mode surface.
- Do not use purple, gradients, or glass blur; this direction is flat-coloured with soft elevation by decision. The one exception is the chat fades: on ChatPage the header is sticky inside the thread's scroll area with a 24px `from-background` to transparent fade below it, and the composer has the matching fade above it, so messages scrolling under either do not end in a hard edge.

## 9 Verification

A UI change is acceptable when these pass:

```bash
node .claude/skills/ui-planning/scripts/contrast-check.mjs frontend/index.css --pair warning-foreground:warning
cd frontend && npm test && npm run lint && npm run build
```

- Contrast: every text pair ≥ 4.5:1 in **both** modes. A `ring` below 3:1 is a failure.
- Grep before declaring done: `frontend/src` for `#` colours and `rgb(` (the `recipes.test.ts` check also fails on these and on any `.css` file under `src/`), and `frontend/index.css` for `/*`. Both should return nothing.
- Both modes and both UI languages rendered and looked at, at 375px and 1280px wide.
