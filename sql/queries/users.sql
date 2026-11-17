-- name: claim_user
-- Insert, or return the user already holding this name (case and outer spaces ignored)
INSERT INTO users (name, last_seen_at) VALUES (%(name)s, now())
ON CONFLICT (name_key) DO UPDATE SET last_seen_at = now()
RETURNING *;

-- name: get_user
SELECT * FROM users WHERE id = %(id)s;
