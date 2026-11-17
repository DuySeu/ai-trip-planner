-- name: block
INSERT INTO quota_blocks (service, blocked_until, reason) VALUES (%(service)s, %(until)s, %(reason)s)
ON CONFLICT (service) DO UPDATE SET blocked_until = excluded.blocked_until, reason = excluded.reason;

-- name: active_block
SELECT blocked_until FROM quota_blocks WHERE service = %(service)s AND blocked_until > now();

-- name: count_tavily_today
-- Each Tavily fetch writes or refreshes one cache row; "today" is the UTC day
SELECT count(*) FROM search_cache
WHERE provider = 'tavily' AND created_at >= date_trunc('day', now(), 'UTC');
