# REQUIREMENT FOR THIS PROJECT

## Tech Stack

- Frontend: React, css, typescript (Vite)
- Backend: Python 3.12+, FastAPI, follow project structure for AI agent system in `/src`
- Database: Postgres 17-alpine, run migrations and sql command in `/sql` (numbered migrations in `sql/migrations`, named queries in `sql/queries`)
- Background jobs: a worker process reading a Postgres job table (no Redis)
- Qdrant (optional, not used in v1)
- AI model: free model from OpenRouter crawl using `sync_models.sh` script, free models only, with a fallback list
- Web search: Tavily
- Weather and place search: Open-Meteo (free, no key)
- Exchange rates: a free daily rate API (ExchangeRate-API open endpoint proposed, terms unverified)
- Excel: openpyxl, filling `data/trip-template.xlsx`
- API-KEY read from `.env`, every setting listed in `.env.example`
- Local run: `docker compose up` starts Postgres, API, worker and web

## Users

- [x] A visitor enters a name to start; no password in v1
- [x] Names are unique, ignoring case and leading or trailing spaces
- [x] A visitor sees the list of trips under their name
- [x] Login (secret key or password) is planned for later and must not need changes to the trip tables

## Functional requirements

- [x] Create a trip plan with user information include: time, budget, group of, style travel, destination
- [x] A visitor who does not know where to go can chat to get destination ideas; a fixed 6-step questionnaire card asks for the missing basics (travel style, group size, budget, origin, when, how long), then the AI suggests up to 3 destinations as cards (why it fits, estimated cost per person, best months), and "Plan this trip" fills the trip form
- [x] The trip form links to that chat ("Not sure where? Get ideas") with what the visitor already entered
- [x] Destination is picked from a place search, anywhere in the world; Vietnam is the default
- [x] Budget is in VND; a trip inside Vietnam uses VND only; a trip abroad uses two currencies, VND and the destination's local currency, with the exchange rate shown and saved with the plan
- [x] Searching the information that related to user input to search web, finding hotel option, weather, transport
- [x] Plan creation runs in the background, shows its progress (researching, planning) and can be retried after a failure
- [x] Weather uses the forecast when the trip is within 16 days, otherwise typical weather for the same dates last year, and says which
- [x] Every price says whether it comes from a source (with a link) or is an estimate; no invented links
- [x] A plan that goes over budget says so and by how much
- [x] Summary and create a excel file for user base on the template `data/trip-template.xlsx`
- [x] The Excel file keeps the template's sheets, formulas and validations, and its expected total matches the plan total
- [x] Allow user to chat, asking about the plan created and ask AI to change base on user changed
- [x] Chat can answer questions about the plan, give general travel advice, look up new information, and change the plan
- [x] Chat can search hotels and tickets (flight, train, bus) for a place; when the open trip and the chat give no dates (or no origin for tickets), a card asks for them
- [x] Chat can open a trip form prefilled from the conversation; Create makes the trip, Cancel closes the form
- [x] One conversation is not tied to one task or one trip: it can discuss any of the visitor's trips and look for a new destination; edits apply to the trip open on screen
- [x] Every change to a plan overwrites it; no history is kept
- [x] Changing dates, number of travelers or origin re-plans the trip; a new destination is a new trip
- [x] Two edits on the same plan at once: the second is rejected and the page reloads the latest plan
- [x] The plan can be exported to Excel
- [x] A visitor can delete a trip

## Non-functional requirements

- [x] display in FE: chatbot for asking for suggestion for travel and ask change the created plan
- [x] display in FE: Create a trip plan that base on the basic form
- [x] UI in English by default, Vietnamese as a second UI language
- [x] The AI replies in the language the visitor writes in (English or Vietnamese)
- [x] Free models only: when the free daily quota runs out, new trips and chat show "try again tomorrow"; viewing and exporting keep working
- [x] When one model is rate-limited, slow or returns broken output, the next model in the list is tried
- [x] At most 6 AI calls per plan creation, counting retries; about 5 web searches per new trip; a chat question about one part (for example transport) searches only that part and does not rerun the whole plan
- [x] Every structured AI output is checked against a schema, with one repair attempt, before it is used
- [x] Search results are cached for 24 hours so repeated trips do not use quota
- [x] Rate limits per IP and per name, a daily trip and message cap, and a global daily ceiling for AI and search calls
- [x] Web content is treated as untrusted data in prompts; AI output can only change a plan through checked edit operations
- [x] Inputs are validated at the API; errors return one JSON shape and never raw exception text
- [x] Trips are kept until their user deletes them; inactive names with no trips are freed after 90 days; IP addresses are not stored in the database
- [ ] JSON logs with request, trip and job ids; a log of every AI call (model, tokens, time, outcome); health and readiness endpoints
- [x] Unit, integration and API tests with a fake AI model and fake search; the test suite makes no real external calls
