-- name: create_trip
INSERT INTO trips (
    user_id, destination_name, destination_country, destination_lat,
    destination_lon, origin, start_date, end_date, travelers, travel_styles,
    budget_amount, budget_scope, local_currency, language, notes, status,
    expires_at
) VALUES (
    %(user_id)s, %(destination_name)s, %(destination_country)s,
    %(destination_lat)s, %(destination_lon)s, %(origin)s, %(start_date)s, %(end_date)s,
    %(travelers)s, %(travel_styles)s, %(budget_amount)s,
    %(budget_scope)s, %(local_currency)s, %(language)s, %(notes)s, 'queued',
    now() + make_interval(days => %(retention_days)s)
)
RETURNING *;

-- name: get_trip
SELECT * FROM trips WHERE id = %(id)s;

-- name: list_trips
SELECT * FROM trips WHERE user_id = %(user_id)s
ORDER BY created_at DESC
LIMIT %(limit)s OFFSET %(offset)s;

-- name: count_trips
SELECT count(*) FROM trips WHERE user_id = %(user_id)s;

-- name: set_status
UPDATE trips SET status = %(status)s, failure_reason = %(failure_reason)s, updated_at = now()
WHERE id = %(id)s;

-- name: touch
UPDATE trips SET updated_at = now(), expires_at = now() + make_interval(days => %(retention_days)s)
WHERE id = %(id)s;

-- name: delete_trip
DELETE FROM trips WHERE id = %(id)s;

-- name: count_trips_today
-- "Today" is the Vietnam calendar day, like the trip date rules
SELECT count(*) FROM trips
WHERE user_id = %(user_id)s AND created_at >= date_trunc('day', now(), 'Asia/Ho_Chi_Minh');

-- name: save_plan
-- Overwrites the plan only if nobody wrote since base_revision
UPDATE trips SET
    plan = %(plan)s,
    total_cost_vnd = %(total_cost_vnd)s,
    over_budget = %(over_budget)s,
    model_id = %(model_id)s,
    plan_revision = plan_revision + 1,
    updated_at = now()
WHERE id = %(id)s AND plan_revision = %(base_revision)s
RETURNING *;

-- name: save_plan_with_request
-- A re-plan: the new request lands together with the plan made from it
UPDATE trips SET
    plan = %(plan)s,
    total_cost_vnd = %(total_cost_vnd)s,
    over_budget = %(over_budget)s,
    model_id = %(model_id)s,
    plan_revision = plan_revision + 1,
    updated_at = now(),
    destination_name = %(destination_name)s,
    destination_country = %(destination_country)s,
    destination_lat = %(destination_lat)s,
    destination_lon = %(destination_lon)s,
    origin = %(origin)s,
    start_date = %(start_date)s,
    end_date = %(end_date)s,
    travelers = %(travelers)s,
    travel_styles = %(travel_styles)s,
    budget_amount = %(budget_amount)s,
    budget_scope = %(budget_scope)s,
    language = %(language)s,
    notes = %(notes)s
WHERE id = %(id)s AND plan_revision = %(base_revision)s
RETURNING *;

-- name: delete_expired_trips
-- Jobs and research rows go with the trip (cascade); llm_calls keep their rows with a null trip
DELETE FROM trips WHERE expires_at < %(now)s;
