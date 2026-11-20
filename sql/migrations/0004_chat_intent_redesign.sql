-- Five intents instead of twelve. The structured part of a message (cards, form state, questionnaire
-- answers) moves to metadata; intent only says which flow answered.
ALTER TABLE messages
    DROP CONSTRAINT messages_intent_check,
    DROP CONSTRAINT messages_suggestions_check;
ALTER TABLE messages RENAME COLUMN suggestions TO metadata;

UPDATE messages SET intent = 'advice'
WHERE intent IN ('travel_advice', 'answer', 'plan_answer');
UPDATE messages SET intent = 'advice', metadata = '{"searched": true}'
WHERE intent = 'trip_research';
UPDATE messages SET intent = 'advice', metadata = '{"clarify": true}'
WHERE intent = 'clarification';
UPDATE messages SET intent = 'edit_plan'
WHERE intent = 'plan_editor';
UPDATE messages
SET intent = 'discover',
    metadata = '{"kind": "questionnaire", "status": "done", "step": 0, "answers": {}, "choices": {}}'
WHERE intent = 'ask';
UPDATE messages
SET intent = 'discover',
    metadata = jsonb_build_object('kind', 'suggestions', 'cards', coalesce(metadata, '[]'))
WHERE intent = 'suggest';
UPDATE messages
SET intent = 'booking_search',
    metadata = jsonb_build_object(
        'kind', 'hotel', 'status', 'results', 'query', '', 'dates', NULL,
        'cards', coalesce(metadata, '[]')
    )
WHERE intent = 'hotel_options';
-- A trip form kept its draft (and the trip id once created) as JSON in content
UPDATE messages
SET metadata = jsonb_build_object(
        'status', CASE intent
            WHEN 'trip_form' THEN 'open'
            WHEN 'created_trip' THEN 'created'
            ELSE 'canceled'
        END,
        'draft', content::jsonb - 'trip_id',
        'trip_id', content::jsonb -> 'trip_id'
    ),
    intent = 'create_trip',
    content = ''
WHERE intent IN ('trip_form', 'created_trip', 'canceled_trip');

ALTER TABLE messages
    ADD CONSTRAINT messages_intent_check CHECK (intent IN (
        'advice', 'discover', 'booking_search', 'create_trip', 'edit_plan'
    )),
    -- coalesce: a CHECK that comes out NULL (no metadata) would pass
    ADD CONSTRAINT messages_create_trip_status_check CHECK (
        intent IS DISTINCT FROM 'create_trip'
        OR coalesce(metadata ->> 'status', '') IN ('open', 'created', 'canceled')
    ),
    ADD CONSTRAINT messages_booking_search_check CHECK (
        intent IS DISTINCT FROM 'booking_search'
        OR (coalesce(metadata ->> 'kind', '') IN ('hotel', 'flight')
            AND coalesce(metadata ->> 'status', '') IN ('need_dates', 'done', 'results'))
    ),
    ADD CONSTRAINT messages_discover_kind_check CHECK (
        intent IS DISTINCT FROM 'discover'
        OR coalesce(metadata ->> 'kind', '') IN ('questionnaire', 'suggestions')
    );
