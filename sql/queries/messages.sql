-- name: add_message
-- clock_timestamp, not now(): two messages saved in one transaction must still sort in order
INSERT INTO messages (conversation_id, role, content, intent, suggestions, created_at)
VALUES (%(conversation_id)s, %(role)s, %(content)s, %(intent)s, %(suggestions)s, clock_timestamp())
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
