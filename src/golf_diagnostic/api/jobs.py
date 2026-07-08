"""In-memory job store and background execution for the API layer.

The store holds Job records keyed by UUID. Each job has an associated
session directory on disk containing uploads, per-request pose cache,
and rendered annotated videos. All three subdirs live under the same
session dir so cleanup is a single ``rmtree``.

Concurrency model
-----------------
* An ``asyncio.Lock`` guards dict-level operations (add, get, remove).
  Individual Job field mutations happen only in the event-loop
  thread at state-transition boundaries, so field-level access does
  not need locking.
* An ``asyncio.Semaphore(1)`` serializes actual pipeline execution.
  HF Spaces free tier is single-container; two ``analyze_swings``
  calls in parallel would just fight for CPU. Queued jobs sit in
  the ``QUEUED`` state until the semaphore is available, which is
  visible to ``GET /jobs/{id}`` — honest queueing.
* Background tasks are tracked in a set to prevent GC of running
  coroutines and to allow orderly cancellation at shutdown.

Job state model
---------------
Coarse for v1: ``queued | processing | done | failed``. See phase 5
notes for why finer-grained progress was deferred until real users
show evidence they need it.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from anthropic import Anthropic

from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.kb.loader import KnowledgeBase
from golf_diagnostic.pipeline import AnalysisResult, analyze_swings

logger = logging.getLogger(__name__)


class JobState(str, Enum):
    """Lifecycle states for an analysis job."""

    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    """Analysis job record.

    ``result`` is populated when state == DONE. ``error`` is a
    user-safe message populated when state == FAILED. Internal
    exception details are logged server-side and NOT put in
    ``error``.
    """

    id: str
    state: JobState
    created_at: datetime
    updated_at: datetime
    session_dir: Path
    symptom: str
    handedness: Handedness
    user_context: str
    n_videos: int
    result: AnalysisResult | None = None
    error: str | None = None

    def touch(self) -> None:
        """Update ``updated_at`` to now (UTC)."""
        self.updated_at = datetime.now(timezone.utc)


class JobStore:
    """Thread-safe in-memory job store."""

    def __init__(self, sessions_root: Path) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._exec_semaphore = asyncio.Semaphore(1)
        self._tasks: set[asyncio.Task] = set()
        self._sessions_root = sessions_root
        self._sessions_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def sessions_root(self) -> Path:
        return self._sessions_root

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id)

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    async def create(
        self,
        symptom: str,
        handedness: Handedness,
        user_context: str,
        n_videos: int,
    ) -> Job:
        """Create a new job with a fresh session directory.

        Layout::

            {sessions_root}/{job_id}/
                uploads/     # user-provided videos
                annotated/   # pipeline-rendered overlays
                pose_cache/  # per-request NPZ cache
        """
        job_id = str(uuid.uuid4())
        session_dir = self._sessions_root / job_id
        (session_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (session_dir / "annotated").mkdir(parents=True, exist_ok=True)
        (session_dir / "pose_cache").mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        job = Job(
            id=job_id,
            state=JobState.QUEUED,
            created_at=now,
            updated_at=now,
            session_dir=session_dir,
            symptom=symptom,
            handedness=handedness,
            user_context=user_context,
            n_videos=n_videos,
        )
        async with self._lock:
            self._jobs[job_id] = job
        logger.info("Job %s: created (symptom=%s, n_videos=%d)",
                    job_id, symptom, n_videos)
        return job

    async def abort(self, job: Job) -> None:
        """Remove a not-yet-started job and delete its session dir.

        Used when upload validation fails mid-stream. Do NOT call on
        a job that is actively processing — the running task holds
        references and expects the session dir to exist.
        """
        async with self._lock:
            self._jobs.pop(job.id, None)
        try:
            shutil.rmtree(job.session_dir, ignore_errors=True)
        except Exception:
            logger.exception("Failed to remove session dir for aborted job %s", job.id)
        logger.info("Job %s: aborted", job.id)

    def spawn(
        self,
        job: Job,
        video_paths: list[Path],
        kb: KnowledgeBase,
        anthropic_client: Anthropic,
    ) -> asyncio.Task:
        """Schedule the background pipeline run for a job.

        Returns the task. The store keeps a reference to prevent GC
        of the running coroutine and to enable orderly cancellation
        at shutdown.
        """
        task = asyncio.create_task(
            self._run_job(job, video_paths, kb, anthropic_client),
            name=f"analyze-{job.id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run_job(
        self,
        job: Job,
        video_paths: list[Path],
        kb: KnowledgeBase,
        anthropic_client: Anthropic,
    ) -> None:
        """Execute ``analyze_swings`` for a job under the exec semaphore.

        While a job holds the semaphore, other jobs stay in QUEUED
        state and are visible to GET /jobs/{id}. Failures are caught
        here and mapped to user-safe error strings; the pipeline's
        own logging captures internal detail.
        """
        async with self._exec_semaphore:
            job.state = JobState.PROCESSING
            job.touch()
            logger.info("Job %s: processing", job.id)
            try:
                result = await asyncio.to_thread(
                    analyze_swings,
                    video_paths=video_paths,
                    symptom=job.symptom,
                    kb=kb,
                    user_context=job.user_context,
                    handedness=job.handedness,
                    cache_dir=job.session_dir / "pose_cache",
                    annotated_output_dir=job.session_dir / "annotated",
                    client=anthropic_client,
                    verbose=True,
                )
                job.result = result
                job.state = JobState.DONE
                job.touch()
                logger.info("Job %s: done", job.id)
            except ValueError as e:
                # ValueError sources in the pipeline:
                # - analyze_swings input validation
                # - segment_swing (P1 < P4 < P7 < P10 ordering)
                # - orchestrator (missing checkpoint key, bad order)
                # None have coaching-quality messages by default.
                # Log the internal detail, surface a canned one.
                logger.warning("Job %s: ValueError: %s", job.id, e)
                job.error = (
                    "We couldn't fully analyze one of your videos. This "
                    "usually means a swing was too short, too dark, or "
                    "shot from a different angle than down-the-line. "
                    "Please check your videos and try again."
                )
                job.state = JobState.FAILED
                job.touch()
            except Exception:
                logger.exception("Job %s: unexpected error", job.id)
                job.error = (
                    "Something went wrong during analysis. Please try "
                    "again. If the problem persists, the service may be "
                    "temporarily unavailable."
                )
                job.state = JobState.FAILED
                job.touch()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup_expired(self, max_age_seconds: float) -> int:
        """Remove terminal jobs older than ``max_age_seconds``.

        Only DONE and FAILED jobs are eligible. QUEUED and PROCESSING
        jobs are left alone regardless of age — canceling in-flight
        work is worse than paying a bit more disk for a slow job.

        Returns the number of jobs removed.
        """
        now = datetime.now(timezone.utc)
        expired: list[Job] = []
        async with self._lock:
            for job_id in list(self._jobs.keys()):
                j = self._jobs[job_id]
                if j.state not in (JobState.DONE, JobState.FAILED):
                    continue
                age = (now - j.updated_at).total_seconds()
                if age > max_age_seconds:
                    expired.append(j)
                    del self._jobs[job_id]

        # Filesystem I/O outside the lock so async access to the
        # store isn't blocked while dirs are torn down.
        for j in expired:
            try:
                shutil.rmtree(j.session_dir, ignore_errors=True)
            except Exception:
                logger.exception("Failed to clean up session dir for job %s", j.id)

        if expired:
            logger.info("Cleaned up %d expired job(s)", len(expired))
        return len(expired)

    async def shutdown(self) -> None:
        """Cancel all in-flight background tasks.

        Called from the lifespan shutdown path. Cancellation is
        best-effort; we wait briefly for tasks to observe it, then
        return regardless.
        """
        if not self._tasks:
            return
        logger.info("Cancelling %d in-flight job task(s)", len(self._tasks))
        for task in list(self._tasks):
            task.cancel()
        # Wait briefly for cancellation to propagate.
        await asyncio.gather(*self._tasks, return_exceptions=True)