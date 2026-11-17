-- name: cache_get
SELECT payload FROM search_cache WHERE key = %(key)s AND expires_at > now();

-- name: cache_put
-- A refetch replaces the expired row and counts as a new call (created_at moves)
INSERT INTO search_cache (key, provider, query, payload, expires_at)
VALUES (%(key)s, %(provider)s, %(query)s, %(payload)s, now() + %(ttl)s)
ON CONFLICT (key) DO UPDATE SET
    provider = excluded.provider,
    query = excluded.query,
    payload = excluded.payload,
    created_at = now(),
    expires_at = excluded.expires_at;

-- name: save_source
INSERT INTO research_results (trip_id, conversation_id, kind, cache_key, title, url, snippet)
VALUES (%(trip_id)s, %(conversation_id)s, %(kind)s, %(cache_key)s, %(title)s, %(url)s, %(snippet)s)
RETURNING *;

-- name: sources_for_trip
SELECT * FROM research_results WHERE trip_id = %(trip_id)s ORDER BY id;
