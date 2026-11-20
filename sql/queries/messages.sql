-- name: add_message
-- clock_timestamp, not now(): two messages saved in one transaction must still sort in order
INSERT INTO messages (conversation_id, role, content, intent, suggestions, created_at)
VALUES (%(conversation_id)s, %(role)s, %(content)s, %(intent)s, %(suggestions)s, clock_timestamp())
RETURNING *;

-- name: get_message
SELECT * FROM messages WHERE id = %(id)s;

-- name: close_trip_form
-- Only an open form closes, so two tabs cannot both use it; no row back means it was already closed
UPDATE messages SET intent = %(intent)s, content = COALESCE(%(content)s, content)
WHERE id = %(id)s AND intent = 'trip_form'
RETURNING *;

-- name: recent_messages
-- The last `limit` messages, returned oldest first
SELECT * FROM (
    SELECT * FROM messages WHERE conversation_id = %(conversation_id)s
    ORDER BY created_at DESC
    LIMIT %(limit)s
) AS recent
ORDER BY created_at;

-- name: count_user_messages_today
-- "Today" is the Vietnam calendar day
SELECT count(*) FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE c.user_id = %(user_id)s AND m.role = 'user'
  AND m.created_at >= date_trunc('day', now(), 'Asia/Ho_Chi_Minh');

-- name: count_intent
SELECT count(*) FROM messages
WHERE conversation_id = %(conversation_id)s AND intent = %(intent)s;

-- name: list_messages
-- Oldest first, for paging through a conversation
SELECT * FROM messages WHERE conversation_id = %(conversation_id)s
ORDER BY created_at
LIMIT %(limit)s OFFSET %(offset)s;

-- name: count_messages
SELECT count(*) FROM messages WHERE conversation_id = %(conversation_id)s;
