-- name: create_conversation
INSERT INTO conversations (user_id, request_draft) VALUES (%(user_id)s, %(draft)s)
RETURNING *;

-- name: get_conversation
SELECT * FROM conversations WHERE id = %(id)s;

-- name: list_conversations
-- Most recently active first; a null limit returns every row
SELECT * FROM conversations WHERE user_id = %(user_id)s
ORDER BY updated_at DESC, created_at DESC
LIMIT %(limit)s OFFSET %(offset)s;

-- name: count_conversations
SELECT count(*) FROM conversations WHERE user_id = %(user_id)s;

-- name: save_draft
UPDATE conversations SET request_draft = %(draft)s WHERE id = %(id)s;

-- name: clear_draft
UPDATE conversations SET request_draft = NULL WHERE id = %(id)s;

-- name: touch_conversation
UPDATE conversations SET updated_at = now() WHERE id = %(id)s;

-- name: rename_conversation
-- updated_at stays, so a rename does not reorder the list
UPDATE conversations SET title = %(title)s WHERE id = %(id)s RETURNING *;

-- name: set_title_if_missing
UPDATE conversations SET title = %(title)s WHERE id = %(id)s AND title IS NULL;

-- name: delete_conversation
DELETE FROM conversations WHERE id = %(id)s;
