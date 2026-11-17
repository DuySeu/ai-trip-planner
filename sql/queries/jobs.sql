-- name: enqueue
INSERT INTO jobs (trip_id, kind, status, request) VALUES (%(trip_id)s, %(kind)s, 'queued', %(request)s)
RETURNING *;

-- name: lease_next
-- A queued job that is due, or a running one whose worker died (lease expired)
UPDATE jobs SET status = 'running', attempts = attempts + 1,
       leased_until = now() + make_interval(secs => %(lease_seconds)s)
WHERE id = (
  SELECT id FROM jobs
  WHERE (status = 'queued' AND run_after <= now())
     OR (status = 'running' AND leased_until < now())
  ORDER BY run_after
  FOR UPDATE SKIP LOCKED
  LIMIT 1)
RETURNING *;

-- name: set_stage
UPDATE jobs SET stage = %(stage)s WHERE id = %(id)s;

-- name: add_llm_calls
UPDATE jobs SET llm_calls_used = llm_calls_used + %(n)s WHERE id = %(id)s;

-- name: finish
UPDATE jobs SET status = %(status)s, last_error = %(last_error)s, leased_until = NULL,
       finished_at = now()
WHERE id = %(id)s;

-- name: requeue
UPDATE jobs SET status = 'queued', run_after = %(run_after)s, last_error = %(last_error)s,
       leased_until = NULL
WHERE id = %(id)s;

-- name: active_job
SELECT * FROM jobs WHERE trip_id = %(trip_id)s AND status IN ('queued', 'running');
