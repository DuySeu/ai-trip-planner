-- name: create_conversation
INSERT INTO conversations (user_id, request_draft) VALUES (%(user_id)s, %(draft)s)
RETURNING *;

-- name: get_conversation
SELECT * FROM conversations WHERE id = %(id)s;

-- name: list_conversations
-- Most recently active first
SELECT * FROM conversations WHERE user_id = %(user_id)s
ORDER BY updated_at DESC, created_at DESC;

-- name: save_draft
UPDATE conversations SET request_draft = %(draft)s WHERE id = %(id)s;

-- name: touch_conversation
UPDATE conversations SET updated_at = now() WHERE id = %(id)s;
