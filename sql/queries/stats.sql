-- name: llm_today
SELECT
    count(*) AS calls,
    coalesce(sum(input_tokens), 0)::bigint AS input_tokens,
    coalesce(sum(output_tokens), 0)::bigint AS output_tokens
FROM llm_calls
WHERE created_at >= date_trunc('day', now(), 'UTC');

-- name: llm_last_hour
-- percentile_cont skips rows with no latency
SELECT
    count(*) AS calls,
    count(*) FILTER (WHERE outcome <> 'ok') AS errors,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_latency_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms
FROM llm_calls
WHERE created_at >= now() - interval '1 hour';

-- name: llm_outcomes_last_hour
SELECT outcome AS key, count(*) AS count
FROM llm_calls
WHERE created_at >= now() - interval '1 hour'
GROUP BY outcome
ORDER BY count DESC, key;

-- name: job_queue
SELECT
    count(*) FILTER (WHERE status = 'queued') AS queued,
    count(*) FILTER (WHERE status = 'running') AS running,
    extract(epoch FROM now() - min(created_at) FILTER (WHERE status = 'queued'))::int AS oldest_queued_s
FROM jobs
WHERE status IN ('queued', 'running');

-- name: plans_last_day
-- Plan time is from enqueue to finish, so it includes the wait in the queue
SELECT
    count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - created_at))
        FILTER (WHERE status = 'succeeded') AS p50_s,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - created_at))
        FILTER (WHERE status = 'succeeded') AS p95_s,
    count(*) FILTER (WHERE status = 'failed') AS failed
FROM jobs
WHERE finished_at >= now() - interval '1 day';

-- name: last_failure
-- The reason code the worker set on the trip, never jobs.last_error (raw exception text)
SELECT t.failure_reason AS reason, j.finished_at
FROM jobs j
JOIN trips t ON t.id = j.trip_id
WHERE j.status = 'failed' AND j.finished_at >= now() - interval '1 day'
ORDER BY j.finished_at DESC
LIMIT 1;

-- name: active_blocks
SELECT service, blocked_until FROM quota_blocks WHERE blocked_until > now() ORDER BY service;

-- name: user_counts
WITH r AS (
    SELECT date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1) AS start
)
SELECT
    count(*) AS total,
    count(*) FILTER (WHERE created_at >= r.start) AS new,
    count(*) FILTER (WHERE last_seen_at >= r.start) AS active
FROM users, r;

-- name: trip_counts
WITH r AS (
    SELECT date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1) AS start
)
SELECT
    count(*) AS created,
    count(*) FILTER (WHERE destination_country = 'VN') AS domestic,
    count(*) FILTER (WHERE destination_country <> 'VN') AS abroad,
    avg(end_date - start_date + 1)::float AS avg_days,
    avg(travelers)::float AS avg_travelers,
    -- budget_amount is always VND (domain.trip_request.budget_total_vnd)
    percentile_cont(0.5) WITHIN GROUP (ORDER BY CASE
        WHEN budget_scope = 'total' THEN budget_amount / travelers ELSE budget_amount
    END) AS median_budget_per_person_vnd,
    count(*) FILTER (WHERE plan IS NOT NULL) AS with_plan,
    count(*) FILTER (WHERE over_budget) AS over_budget
FROM trips, r
WHERE created_at >= r.start;

-- name: trip_statuses
SELECT status AS key, count(*) AS count
FROM trips
WHERE created_at >= date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1)
GROUP BY status
ORDER BY count DESC, key;

-- name: daily
-- Every day of the range, empty days as 0
WITH r AS (
    SELECT
        (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS today,
        date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1) AS start
), days AS (
    SELECT generate_series(r.today - (%(days)s::int - 1), r.today, interval '1 day')::date AS day FROM r
), trip_days AS (
    SELECT (created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS day, count(*) AS n
    FROM trips, r WHERE created_at >= r.start GROUP BY 1
), message_days AS (
    SELECT (created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS day, count(*) AS n
    FROM messages, r WHERE role = 'user' AND created_at >= r.start GROUP BY 1
)
SELECT d.day, coalesce(t.n, 0) AS trips, coalesce(m.n, 0) AS messages
FROM days d
LEFT JOIN trip_days t ON t.day = d.day
LEFT JOIN message_days m ON m.day = d.day
ORDER BY d.day;

-- name: chat_counts
WITH r AS (
    SELECT date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1) AS start
)
SELECT
    (SELECT count(*) FROM conversations WHERE created_at >= r.start) AS conversations,
    (SELECT count(*) FROM messages WHERE role = 'user' AND created_at >= r.start) AS messages
FROM r;

-- name: intents
SELECT intent AS key, count(*) AS count
FROM messages
WHERE role = 'assistant' AND intent IS NOT NULL
  AND created_at >= date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1)
GROUP BY intent
ORDER BY count DESC, key;

-- name: trip_forms
SELECT metadata ->> 'status' AS key, count(*) AS count
FROM messages
WHERE intent = 'create_trip'
  AND created_at >= date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1)
GROUP BY 1
ORDER BY count DESC, key;

-- name: destinations
SELECT destination_name AS name, destination_country AS country, count(*) AS trips
FROM trips
WHERE created_at >= date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1)
GROUP BY destination_name, destination_country
ORDER BY trips DESC, name
LIMIT 10;

-- name: styles
SELECT style AS key, count(*) AS count
FROM trips, unnest(travel_styles) AS style
WHERE created_at >= date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1)
GROUP BY style
ORDER BY count DESC, key;

-- name: models
SELECT model_id, count(*) AS calls, count(*) FILTER (WHERE outcome <> 'ok') AS errors
FROM llm_calls
WHERE created_at >= date_trunc('day', now(), 'Asia/Ho_Chi_Minh') - make_interval(days => %(days)s::int - 1)
GROUP BY model_id
ORDER BY calls DESC, model_id;
