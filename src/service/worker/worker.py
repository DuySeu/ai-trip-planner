"""The worker process: leases generate_plan jobs one at a time and runs the daily cleanup.

Run (from the repo root): PYTHONPATH=src uv run python -m service.worker.worker
"""

from __future__ import annotations

import functools
import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import FrameType

import httpx
import psycopg
from dotenv import load_dotenv

from core.exceptions import NotFound
from core.logger import configure_logging
from core.settings import load_settings
from core.wiring import build_router
from db.pool import open_pool
from db.repositories import jobs
from service.tavily.search import build_web_search
from service.worker.cleanup import run_cleanup
from service.worker.generate_plan import JobDeps, build_research_deps, run_generate_plan

logger = logging.getLogger(__name__)

POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 60.0
CLEANUP_EVERY = timedelta(hours=24)
HTTP_TIMEOUT_S = 10.0
# Time a lease may outlive the slowest job: every LLM call at its timeout, plus research and saving
LEASE_SLACK_S = 120


# Make SIGTERM and SIGINT ask the worker to stop after the job it is running
def stop_on_signal(stop: threading.Event) -> None:
    # Only sets the event; the loop notices it between jobs
    def handler(signum: int, frame: FrameType | None) -> None:
        logger.info("signal %s received, stopping after the current job", signum)
        stop.set()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


# Lease and run jobs until stop is set; a job that is running finishes first
def run_worker(
    deps: JobDeps,
    worker_id: str,
    poll_seconds: float,
    stop: threading.Event,
    cleanup_every: timedelta = CLEANUP_EVERY,
) -> None:
    settings = deps.settings
    lease_seconds = settings.llm_calls_per_job * settings.planner_timeout_s + LEASE_SLACK_S
    logger.info("worker %s started", worker_id)

    next_cleanup = time.monotonic()
    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    while not stop.is_set():
        # Daily cleanup, also once at start; a database error is logged, never fatal
        if time.monotonic() >= next_cleanup:
            next_cleanup = time.monotonic() + cleanup_every.total_seconds()
            try:
                with deps.pool.connection() as conn:
                    counts = run_cleanup(conn, deps.now(), settings.user_inactive_days)
                logger.info("cleanup deleted %s", counts)
            except psycopg.Error:
                logger.exception("cleanup failed")

        if time.monotonic() >= next_heartbeat:
            next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
            logger.info("worker %s heartbeat", worker_id)

        # Take the next due job; sleep when there is none
        try:
            with deps.pool.connection() as conn:
                job = jobs.lease_next(conn, worker_id, lease_seconds)
        except psycopg.Error:
            logger.exception("leasing a job failed")
            stop.wait(poll_seconds)
            continue
        if job is None:
            stop.wait(poll_seconds)
            continue

        # The job settles its own failures; what escapes is logged and its lease expires
        try:
            run_generate_plan(job, deps)
        except (NotFound, psycopg.Error, ValueError):
            logger.exception("job %s crashed", job.id)
    logger.info("worker %s stopped", worker_id)


# Build the real services from the environment and run until SIGTERM
def main() -> None:
    load_dotenv()
    settings = load_settings(os.environ)
    configure_logging("INFO")

    now: Callable[[], datetime] = functools.partial(datetime.now, UTC)
    pool = open_pool(settings.db.conninfo())
    stop = threading.Event()
    stop_on_signal(stop)
    with httpx.Client(timeout=HTTP_TIMEOUT_S) as http:
        deps = JobDeps(
            settings=settings,
            pool=pool,
            router=build_router(settings, pool, now),
            research=build_research_deps(
                settings, pool, http, build_web_search(settings, pool, now), now
            ),
            now=now,
        )
        try:
            run_worker(deps, f"{socket.gethostname()}-{os.getpid()}", POLL_SECONDS, stop)
        finally:
            pool.close()


if __name__ == "__main__":
    main()
