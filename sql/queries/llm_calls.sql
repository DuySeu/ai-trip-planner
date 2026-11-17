-- name: log_call
INSERT INTO llm_calls (
    trip_id, conversation_id, message_id, purpose, model_id, input_tokens, output_tokens,
    latency_ms, outcome, error
) VALUES (
    %(trip_id)s, %(conversation_id)s, %(message_id)s, %(purpose)s, %(model_id)s,
    %(input_tokens)s, %(output_tokens)s, %(latency_ms)s, %(outcome)s, %(error)s
);

-- name: count_today
-- "Today" is the UTC day, closest to the provider's daily reset; purposes NULL means all
SELECT count(*) FROM llm_calls
WHERE created_at >= date_trunc('day', now(), 'UTC')
  AND (%(purposes)s::text[] IS NULL OR purpose = ANY(%(purposes)s::text[]));
