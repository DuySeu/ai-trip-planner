-- name: claim_user
-- Insert, or return the user already holding this name (case and outer spaces ignored)
INSERT INTO users (name, last_seen_at) VALUES (%(name)s, now())
ON CONFLICT (name_key) DO UPDATE SET last_seen_at = now()
RETURNING *;

-- name: get_user
SELECT * FROM users WHERE id = %(id)s;

-- name: delete_idle_users
-- Users with no trips and no activity since the cutoff; their conversations and messages cascade.
-- One statement, so the conversation count is exactly what the delete removed.
WITH idle AS (
    SELECT u.id FROM users u
    WHERE coalesce(u.last_seen_at, u.created_at) < %(cutoff)s
      AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.user_id = u.id)
), idle_conversations AS (
    SELECT count(*) AS n FROM conversations WHERE user_id IN (SELECT id FROM idle)
), deleted AS (
    DELETE FROM users WHERE id IN (SELECT id FROM idle) RETURNING id
)
SELECT (SELECT count(*) FROM deleted) AS users, (SELECT n FROM idle_conversations) AS conversations;
