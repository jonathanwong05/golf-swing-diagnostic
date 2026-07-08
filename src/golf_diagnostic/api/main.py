"""FastAPI application for the golf swing diagnostic tool.

Endpoints
---------
- ``GET /``                                  — health + config info
- ``POST /analyze``                          — upload swings, start a job
- ``GET /jobs/{job_id}``                     — poll for job state / result
- ``GET /jobs/{job_id}/videos/{filename}``   — serve annotated video

Environment variables
---------------------
- ``ANTHROPIC_API_KEY`` (required)
- ``GOLF_KB_DIR`` (optional, default ``kb``)
- ``GOLF_SESSIONS_DIR`` (optional, default ``/tmp/golf-analysis``)

Local development::

    uvicorn golf_diagnostic.api.main:app --reload

Production (HF Spaces expects port 7860)::

    uvicorn golf_diagnostic.api.main:app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from golf_diagnostic.api.jobs import Job, JobState, JobStore
from golf_diagnostic.diagnosis.output_schema import (
    CauseExplanation,
    DiagnosticOutput,
)
from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.kb.loader import KnowledgeBase, load_kb

logger = logging.getLogger(__name__)

# --- Upload constraints ---
# Caps chosen for headroom over a typical 3s 60fps iPhone clip
# (~20-25 MB at 1080p). 100 MB per file covers 4K captures and
# longer clips; 500 MB total covers 5 videos at that per-file cap.
# Adjust downward if HF Spaces enforces a smaller request-body limit
# in deployment.
MIN_VIDEOS = 1
MAX_VIDEOS = 5
MAX_FILE_BYTES = 100 * 1024 * 1024   # 100 MB
MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB
ALLOWED_EXTENSIONS = frozenset({".mov", ".mp4", ".m4v"})
MAX_CONTEXT_CHARS = 500

# --- Cleanup ---
JOB_TTL_SECONDS = 60 * 60          # 1 hour
CLEANUP_INTERVAL_SECONDS = 15 * 60  # every 15 minutes


# ----------------------------------------------------------------------
# Lifespan
# ----------------------------------------------------------------------

async def _cleanup_loop(store: JobStore) -> None:
    """Periodic cleanup task; cancelled at shutdown."""
    logger.info(
        "Cleanup task started (interval=%ds, ttl=%ds)",
        CLEANUP_INTERVAL_SECONDS,
        JOB_TTL_SECONDS,
    )
    try:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            try:
                await store.cleanup_expired(JOB_TTL_SECONDS)
            except Exception:
                logger.exception("cleanup_expired failed; will retry next tick")
    except asyncio.CancelledError:
        logger.info("Cleanup task stopping")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # KB
    kb_dir = Path(os.environ.get("GOLF_KB_DIR", "kb")).resolve()
    if not kb_dir.exists():
        raise RuntimeError(
            f"KB directory not found: {kb_dir}. "
            "Set GOLF_KB_DIR or run uvicorn from the project root."
        )
    logger.info("Loading KB from %s", kb_dir)
    kb = load_kb(kb_dir)
    loaded = sorted(kb.loaded_symptoms())
    logger.info("KB loaded: %d symptoms (%s)", len(loaded), ", ".join(loaded))

    # Anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it before starting the server."
        )
    client = Anthropic()
    logger.info("Anthropic client instantiated")

    # Job store
    sessions_root = Path(
        os.environ.get("GOLF_SESSIONS_DIR", "/tmp/golf-analysis")
    ).resolve()
    store = JobStore(sessions_root)
    logger.info("Sessions root: %s", sessions_root)

    cleanup_task = asyncio.create_task(_cleanup_loop(store), name="cleanup-loop")

    app.state.kb = kb
    app.state.kb_dir = kb_dir
    app.state.anthropic_client = client
    app.state.job_store = store

    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await store.shutdown()


app = FastAPI(
    title="Golf Swing Diagnostic API",
    description=(
        "Upload 3-5 down-the-line iron swing videos and receive a "
        "personalized diagnosis for a reported ball-flight symptom."
    ),
    version="0.5.0-dev",
    lifespan=lifespan,
)


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------

@app.get("/")
async def health(request: Request) -> dict[str, Any]:
    """Liveness + readiness check.

    Confirms the KB loaded and the Anthropic client instantiated.
    Does NOT make a real Anthropic call — health probes should not
    spend money, and a live call adds latency for no diagnostic gain.
    """
    kb: KnowledgeBase = request.app.state.kb
    store: JobStore = request.app.state.job_store
    return {
        "status": "ok",
        "loaded_symptoms": sorted(kb.loaded_symptoms()),
        "kb_dir": str(request.app.state.kb_dir),
        "anthropic_client_ready": request.app.state.anthropic_client is not None,
        "sessions_root": str(store.sessions_root),
        "upload_limits": {
            "min_videos": MIN_VIDEOS,
            "max_videos": MAX_VIDEOS,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES,
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
            "max_context_chars": MAX_CONTEXT_CHARS,
        },
    }


# ----------------------------------------------------------------------
# Upload validation and streaming
# ----------------------------------------------------------------------

def _validate_form(
    videos: list[UploadFile],
    symptom: str,
    handedness: str,
    user_context: str,
    loaded_symptoms: set[str],
) -> tuple[Handedness, list[str]]:
    """Validate form fields and file metadata.

    Does NOT read file bodies. Returns ``(parsed_handedness, errors)``;
    empty error list means OK. Runs before we touch the filesystem.
    """
    errors: list[str] = []

    # Symptom
    if symptom not in loaded_symptoms:
        errors.append(
            f"Unsupported symptom '{symptom}'. "
            f"Supported: {', '.join(sorted(loaded_symptoms))}."
        )

    # Handedness
    handedness_lc = (handedness or "right").strip().lower()
    try:
        parsed = Handedness(handedness_lc)
    except ValueError:
        errors.append(
            f"Invalid handedness '{handedness}'. Use 'right' or 'left'."
        )
        parsed = Handedness.RIGHT_HANDED  # placeholder; won't be used

    # File count
    if len(videos) < MIN_VIDEOS:
        errors.append(f"At least {MIN_VIDEOS} video required.")
    elif len(videos) > MAX_VIDEOS:
        errors.append(f"At most {MAX_VIDEOS} videos allowed; got {len(videos)}.")

    # File extensions
    for v in videos:
        if not v.filename:
            errors.append("A file was uploaded with no filename.")
            continue
        ext = Path(v.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(
                f"File '{v.filename}' has unsupported extension '{ext}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            )

    # User context length
    if len(user_context) > MAX_CONTEXT_CHARS:
        errors.append(
            f"user_context exceeds {MAX_CONTEXT_CHARS} chars "
            f"({len(user_context)})."
        )

    return parsed, errors


async def _stream_upload_to_disk(
    upload: UploadFile,
    dest: Path,
    remaining_total_bytes: int,
) -> int:
    """Stream an upload to disk with a running byte cap.

    Enforces both the per-file cap and the remaining-total budget.
    On cap breach, deletes the partial file and raises 413.
    """
    bytes_written = 0
    with dest.open("wb") as f:
        while True:
            chunk = await upload.read(64 * 1024)  # 64 KB
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > MAX_FILE_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"File '{upload.filename}' exceeds per-file cap of "
                        f"{MAX_FILE_BYTES // (1024 * 1024)} MB."
                    ),
                )
            if bytes_written > remaining_total_bytes:
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Total upload size exceeds cap of "
                        f"{MAX_TOTAL_BYTES // (1024 * 1024)} MB."
                    ),
                )
            f.write(chunk)
    return bytes_written


# ----------------------------------------------------------------------
# POST /analyze
# ----------------------------------------------------------------------

@app.post("/analyze")
async def analyze(
    request: Request,
    videos: list[UploadFile] = File(...),
    symptom: str = Form(...),
    handedness: str = Form("right"),
    user_context: str = Form(""),
) -> dict[str, Any]:
    """Accept uploads, create a job, kick off background analysis."""
    kb: KnowledgeBase = request.app.state.kb
    store: JobStore = request.app.state.job_store
    anthropic_client: Anthropic = request.app.state.anthropic_client

    # Cheap validation before touching disk.
    loaded_symptoms = set(kb.loaded_symptoms())
    parsed_handedness, errors = _validate_form(
        videos, symptom, handedness, user_context, loaded_symptoms
    )
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    # Create job + session dir up front so streaming has a home.
    job = await store.create(
        symptom=symptom,
        handedness=parsed_handedness,
        user_context=user_context,
        n_videos=len(videos),
    )
    uploads_dir = job.session_dir / "uploads"

    # Stream files to disk with the running total cap. Names are
    # controlled by us (index-based) — original filenames come from
    # untrusted input, so we don't use them on disk.
    total_bytes = 0
    saved_paths: list[Path] = []
    try:
        for idx, upload in enumerate(videos, start=1):
            ext = Path(upload.filename or "").suffix.lower()
            dest = uploads_dir / f"swing_{idx:02d}{ext}"
            remaining = MAX_TOTAL_BYTES - total_bytes
            written = await _stream_upload_to_disk(upload, dest, remaining)
            total_bytes += written
            saved_paths.append(dest)
            logger.info(
                "Job %s: saved %s (%d bytes)",
                job.id, dest.name, written,
            )
    except HTTPException:
        # Roll back the session dir + store entry so partial state
        # doesn't linger until the next cleanup tick.
        await store.abort(job)
        raise

    # Fire-and-forget the background pipeline. The store keeps a
    # task reference, so the coroutine won't be GC'd mid-flight.
    store.spawn(job, saved_paths, kb, anthropic_client)

    return {
        "job_id": job.id,
        "state": job.state.value,
        "status_url": f"/jobs/{job.id}",
    }


# ----------------------------------------------------------------------
# GET /jobs/{job_id}
# ----------------------------------------------------------------------

def _resolve_explanation(
    exp: CauseExplanation,
    kb: KnowledgeBase,
    symptom: str,
) -> dict[str, Any]:
    """Resolve KB indices (feel_id, drill_ids) into concrete objects."""
    causes_by_id = {c.cause_id: c for c in kb.get_causes(symptom)}
    cause = causes_by_id[exp.cause_id]
    feel = cause.feels[exp.feel_id]
    drills = [cause.drills[i] for i in exp.drill_ids]
    return {
        "cause_id": exp.cause_id,
        "cause_description": cause.description,
        "cause_category": cause.category,
        "technical_explanation": exp.technical_explanation,
        "bridge_to_feel": exp.bridge_to_feel,
        "feel": {
            "text": feel.feel,
            "best_for": feel.best_for,
            "why_it_works": feel.why_it_works,
        },
        "drills": [
            {"name": d.name, "youtube_url": d.youtube_url} for d in drills
        ],
        "fix": {"technical_instruction": cause.fix.technical_instruction},
    }


def _resolve_diagnosis(
    diagnosis: DiagnosticOutput,
    kb: KnowledgeBase,
    symptom: str,
) -> dict[str, Any]:
    """Convert LLM output (indices) into an API-facing payload (resolved).

    The frontend gets a self-contained JSON blob with feel text and
    drill URLs already substituted. No KB access needed on the
    client side.
    """
    return {
        "summary": diagnosis.summary,
        "primary": (
            _resolve_explanation(diagnosis.primary, kb, symptom)
            if diagnosis.primary is not None
            else None
        ),
        "secondary": [
            _resolve_explanation(exp, kb, symptom)
            for exp in diagnosis.secondary
        ],
        "fallback_message": diagnosis.fallback_message,
    }


def _serialize_job(job: Job, kb: KnowledgeBase) -> dict[str, Any]:
    """Build the API response payload for a job.

    Shape stays consistent across states so the frontend can render
    from one schema; state-specific fields (``result``, ``error``)
    appear only when populated.
    """
    out: dict[str, Any] = {
        "id": job.id,
        "state": job.state.value,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "symptom": job.symptom,
        "handedness": job.handedness.value,
        "n_videos": job.n_videos,
    }
    if job.state == JobState.DONE and job.result is not None:
        result = job.result
        out["result"] = {
            "diagnosis": _resolve_diagnosis(result.diagnosis, kb, job.symptom),
            "annotated_video_urls": [
                f"/jobs/{job.id}/videos/{p.name}"
                for p in result.annotated_video_paths
            ],
            # Debug trail: cause_id + score for each ranked cause.
            # Useful for observability during Phase 5; frontend may
            # ignore it.
            "top_ranked_causes": [
                {"cause_id": rc.cause.cause_id, "score": rc.score}
                for rc in result.ranked_causes
            ],
        }
    elif job.state == JobState.FAILED:
        out["error"] = job.error
    return out


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    store: JobStore = request.app.state.job_store
    kb: KnowledgeBase = request.app.state.kb
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _serialize_job(job, kb)


# ----------------------------------------------------------------------
# GET /jobs/{job_id}/videos/{filename}
# ----------------------------------------------------------------------

@app.get("/jobs/{job_id}/videos/{filename}")
async def get_job_video(
    job_id: str,
    filename: str,
    request: Request,
) -> FileResponse:
    """Serve an annotated video for a completed job.

    Path traversal defense: resolve the requested path inside the
    annotated dir and verify it stays there. Filenames come from
    untrusted URL input, so we never trust them directly.
    """
    store: JobStore = request.app.state.job_store
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.state != JobState.DONE:
        raise HTTPException(
            status_code=404, detail="Videos not available (job not done)."
        )

    annotated_dir = (job.session_dir / "annotated").resolve()
    candidate = (annotated_dir / filename).resolve()
    try:
        candidate.relative_to(annotated_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Video not found.")

    return FileResponse(candidate, media_type="video/mp4")