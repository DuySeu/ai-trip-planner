-- Initial schema. See docs/superpowers/specs/2026-11-16-ai-trip-planner-design.md, section "Database".
-- Enum-like columns are text + CHECK so adding a value is a one-line migration.

CREATE TABLE users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 50),
    -- The duplicate-name rule: case and surrounding spaces ignored (needs the builtin C.UTF-8 locale for non-ASCII)
    name_key     text GENERATED ALWAYS AS (lower(btrim(name))) STORED UNIQUE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz
);

CREATE TABLE trips (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    destination_name    text NOT NULL CHECK (char_length(destination_name) BETWEEN 1 AND 200),
    destination_country char(2) NOT NULL CHECK (destination_country ~ '^[A-Z]{2}$'),
    destination_lat     double precision NOT NULL CHECK (destination_lat BETWEEN -90 AND 90),
    destination_lon     double precision NOT NULL CHECK (destination_lon BETWEEN -180 AND 180),
    origin              text NOT NULL CHECK (char_length(origin) BETWEEN 1 AND 200),
    start_date          date NOT NULL,
    end_date            date NOT NULL,
    travelers           int NOT NULL CHECK (travelers BETWEEN 1 AND 50),
    travel_styles       text[] NOT NULL CHECK (
        cardinality(travel_styles) >= 1
        AND travel_styles <@ ARRAY['relax', 'adventure', 'culture', 'food', 'nature', 'nightlife', 'shopping', 'luxury', 'budget']
    ),
    budget_amount       numeric(14, 2) NOT NULL CHECK (budget_amount > 0),
    budget_scope        text NOT NULL CHECK (budget_scope IN ('per_person', 'total')),
    local_currency      char(3) CHECK (local_currency ~ '^[A-Z]{3}$'),
    language            text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'vi')),
    notes               text CHECK (char_length(notes) <= 2000),
    status              text NOT NULL CHECK (status IN ('queued', 'researching', 'planning', 'ready', 'failed')),
    failure_reason      text,
    -- The current plan, overwritten on every edit or re-plan; no history is kept
    plan                jsonb CHECK (jsonb_typeof(plan) = 'object'),
    total_cost_vnd      numeric(14, 2) CHECK (total_cost_vnd >= 0),
    over_budget         boolean,
    model_id            text,
    -- Bumped on every overwrite; an edit applies only if the client saw the latest one
    plan_revision       int NOT NULL DEFAULT 0 CHECK (plan_revision >= 0),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    CHECK (end_date >= start_date),
    -- At most 30 days, both ends included
    CHECK (end_date - start_date < 30),
    -- Domestic trips use VND only; trips abroad always have a local currency
    CHECK ((destination_country = 'VN') = (local_currency IS NULL)),
    -- The plan and its totals are set together
    CHECK (num_nulls(plan, total_cost_vnd, over_budget) IN (0, 3))
);

CREATE INDEX trips_user_id_idx ON trips (user_id, created_at DESC);
CREATE INDEX trips_expires_at_idx ON trips (expires_at);

-- Not tied to one task or one trip: any conversation reads every trip of its user. Lives until its user is deleted.
CREATE TABLE conversations (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title         text CHECK (char_length(title) <= 80),
    request_draft jsonb CHECK (request_draft IS NULL OR jsonb_typeof(request_draft) = 'object'),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX conversations_user_id_idx ON conversations (user_id, created_at DESC);

CREATE TABLE messages (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id   uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role              text NOT NULL CHECK (role IN ('user', 'assistant')),
    content           text NOT NULL,
    intent            text CHECK (intent IN (
        'plan_answer', 'plan_editor', 'trip_research', 'travel_advice', 'clarification',
        'ask', 'suggest', 'answer'
    )),
    suggestions       jsonb CHECK (suggestions IS NULL OR jsonb_typeof(suggestions) = 'array'),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (role <> 'user' OR char_length(content) BETWEEN 1 AND 4000)
);

CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at);

CREATE TABLE jobs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id        uuid NOT NULL REFERENCES trips (id) ON DELETE CASCADE,
    kind           text NOT NULL CHECK (kind IN ('generate_plan')),
    status         text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    stage          text CHECK (stage IN ('researching', 'planning', 'validating')),
    attempts       int NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts   int NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    llm_calls_used int NOT NULL DEFAULT 0 CHECK (llm_calls_used >= 0),
    run_after      timestamptz NOT NULL DEFAULT now(),
    leased_until   timestamptz,
    -- New request for a re-plan; written to trips together with the new plan, so trips never pairs a new request with an old plan
    request        jsonb CHECK (request IS NULL OR jsonb_typeof(request) = 'object'),
    last_error     text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz
);

-- One active job per trip
CREATE UNIQUE INDEX jobs_one_active_per_trip ON jobs (trip_id) WHERE status IN ('queued', 'running');
CREATE INDEX jobs_poll_idx ON jobs (status, run_after);
CREATE INDEX jobs_trip_id_idx ON jobs (trip_id);

CREATE TABLE search_cache (
    key        text PRIMARY KEY,
    provider   text NOT NULL CHECK (provider IN ('tavily', 'open_meteo', 'open_meteo_geocoding', 'exchange_rate')),
    query      text NOT NULL,
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX search_cache_expires_idx ON search_cache (expires_at);
CREATE INDEX search_cache_provider_created_idx ON search_cache (provider, created_at);

CREATE TABLE research_results (
    -- This id is the source_id that plans cite
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trip_id         uuid REFERENCES trips (id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES conversations (id) ON DELETE CASCADE,
    kind            text NOT NULL CHECK (kind IN (
        'weather', 'accommodation', 'transport', 'local_transport', 'activities', 'food', 'chat'
    )),
    cache_key       text REFERENCES search_cache (key) ON DELETE SET NULL,
    title           text,
    url             text,
    snippet         text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    -- Owned by a trip or by a discovery conversation, never both
    CHECK (num_nonnulls(trip_id, conversation_id) = 1)
);

CREATE INDEX research_results_trip_idx ON research_results (trip_id);
CREATE INDEX research_results_conversation_idx ON research_results (conversation_id);

CREATE TABLE llm_calls (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trip_id         uuid REFERENCES trips (id) ON DELETE SET NULL,
    conversation_id uuid REFERENCES conversations (id) ON DELETE SET NULL,
    -- Chat calls: the user message that triggered them (it is saved before any call, unlike the reply)
    message_id      uuid REFERENCES messages (id) ON DELETE SET NULL,
    purpose         text NOT NULL CHECK (purpose IN (
        'generate', 'repair', 'classify', 'edit', 'answer', 'discover', 'suggest'
    )),
    model_id        text NOT NULL,
    input_tokens    int,
    output_tokens   int,
    latency_ms      int,
    outcome         text NOT NULL CHECK (outcome IN (
        'ok', 'rate_limited', 'quota_exhausted', 'timeout', 'provider_error', 'invalid_output'
    )),
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX llm_calls_created_idx ON llm_calls (created_at);
CREATE INDEX llm_calls_message_idx ON llm_calls (message_id);

CREATE TABLE quota_blocks (
    service       text PRIMARY KEY CHECK (service IN ('openrouter', 'tavily')),
    blocked_until timestamptz NOT NULL,
    reason        text
);
