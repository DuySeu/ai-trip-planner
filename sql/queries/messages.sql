-- name: add_message
-- clock_timestamp, not now(): two messages saved in one transaction must still sort in order
INSERT INTO messages (conversation_id, role, content, intent, metadata, created_at)
VALUES (%(conversation_id)s, %(role)s, %(content)s, %(intent)s, %(metadata)s, clock_timestamp())
RETURNING *;

-- name: get_message
SELECT * FROM messages WHERE id = %(id)s;

-- name: lock_message
-- Read a card to change it; a second change of the same card waits here until the first commits
SELECT * FROM messages WHERE id = %(id)s FOR UPDATE;

-- name: update_open_metadata
-- Replace the metadata only while it still holds every key of expect, so two tabs cannot both move
-- one card on; no row back means it already moved
UPDATE messages SET metadata = %(metadata)s
WHERE id = %(id)s AND metadata @> %(expect)s
RETURNING *;

-- name: find_open_questionnaire
SELECT * FROM messages
WHERE conversation_id = %(conversation_id)s AND intent = 'discover'
  AND metadata @> '{"kind": "questionnaire", "status": "open"}'
ORDER BY created_at DESC
LIMIT 1;

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

-- name: list_messages
-- Oldest first, for paging through a conversation
SELECT * FROM messages WHERE conversation_id = %(conversation_id)s
ORDER BY created_at
LIMIT %(limit)s OFFSET %(offset)s;

-- name: count_messages
SELECT count(*) FROM messages WHERE conversation_id = %(conversation_id)s;
