"""FastAPI application for the golf swing diagnostic tool.

Endpoints
---------
JSON API:
- ``GET /``                                  — health + config info
- ``POST /analyze``                          — upload swings, start a job
- ``GET /jobs/{job_id}``                     — poll for job state / result
- ``GET /jobs/{job_id}/videos/{filename}``   — serve annotated video

Browser (HTML):
- ``GET /app``                               — upload page
- ``GET /app/jobs/{job_id}``                 — result page (shareable URL)
- ``GET /app/jobs/{job_id}/partial``         — result fragment for JS refresh

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

from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from golf_diagnostic.api.jobs import Job, JobState, JobStore
from golf_diagnostic.diagnosis.matcher import collect_unique_causes
from golf_diagnostic.diagnosis.output_schema import (
    CauseExplanation,
    DiagnosticOutput,
)
from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.kb.loader import Cause, KnowledgeBase, load_kb

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

# --- Templates / static ---
# Resolve relative to this file so `uvicorn` can be invoked from any
# cwd. Both dirs live next to main.py inside the api/ package.
_MODULE_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _MODULE_DIR / "templates"
_STATIC_DIR = _MODULE_DIR / "static"

templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


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
        "personalized diagnosis. A ball-flight symptom is optional — "
        "omit it to receive general analysis of your swing."
    ),
    version="0.5.2-dev",
    lifespan=lifespan,
)

# Static assets (CSS, JS). Path resolved at import time.
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
else:
    logger.warning(
        "Static directory not found at %s — /static endpoint unmounted. "
        "Templates that reference it will 404 on asset requests.",
        _STATIC_DIR,
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
    symptom: str | None,
    handedness: str,
    user_context: str,
    loaded_symptoms: set[str],
) -> tuple[Handedness, list[str]]:
    """Validate form fields and file metadata.

    Does NOT read file bodies. Returns ``(parsed_handedness, errors)``;
    empty error list means OK. Runs before we touch the filesystem.

    ``symptom=None`` signals general mode and is valid; symptom
    validation only applies when a specific symptom was submitted.
    """
    errors: list[str] = []

    # Symptom — only validate when provided (None = general mode)
    if symptom is not None and symptom not in loaded_symptoms:
        errors.append(
            f"Unsupported symptom '{symptom}'. "
            f"Supported: {', '.join(sorted(loaded_symptoms))}. "
            "Omit the symptom field for general analysis."
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
    symptom: str | None = Form(None),
    handedness: str = Form("right"),
    user_context: str = Form(""),
) -> dict[str, Any]:
    """Accept uploads, create a job, kick off background analysis.

    The ``symptom`` field is optional. Absent, empty, or whitespace-
    only values route through general-mode analysis (symptom-agnostic
    ranking across every loaded KB). Any non-empty value is validated
    against the loaded symptoms list.
    """
    kb: KnowledgeBase = request.app.state.kb
    store: JobStore = request.app.state.job_store
    anthropic_client: Anthropic = request.app.state.anthropic_client

    # Normalize symptom: treat missing / empty / whitespace-only as
    # general mode. Downstream code sees ``str | None`` uniformly.
    normalized_symptom = symptom.strip() if symptom else ""
    resolved_symptom: str | None = normalized_symptom or None

    # Cheap validation before touching disk.
    loaded_symptoms = set(kb.loaded_symptoms())
    parsed_handedness, errors = _validate_form(
        videos, resolved_symptom, handedness, user_context, loaded_symptoms
    )
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    # Create job + session dir up front so streaming has a home.
    job = await store.create(
        symptom=resolved_symptom,
        handedness=parsed_handedness,
        user_context=user_context,
        n_videos=len(videos),
    )
    uploads_dir = job.session_dir / "uploads"
    mode_label = "symptom-mode" if resolved_symptom else "general-mode"
    logger.info(
        "Job %s created: %s, n_videos=%d, symptom=%s, handedness=%s",
        job.id, mode_label, len(videos),
        resolved_symptom or "(none)",
        parsed_handedness.value,
    )

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

def _lookup_causes_by_id(
    kb: KnowledgeBase,
    symptom: str | None,
) -> dict[str, Cause]:
    """Build the ``cause_id -> Cause`` map used to resolve LLM output.

    Symptom mode uses ``kb.get_causes(symptom)`` — the LLM only saw
    that symptom's causes. General mode uses ``collect_unique_causes``
    — the LLM saw the pooled set (union of feels/drills, identical
    diagnostic content). ``cause_id`` values are globally unique in
    the KB, so both lookups resolve cited causes unambiguously.
    """
    if symptom is None:
        return {c.cause_id: c for c in collect_unique_causes(kb)}
    return {c.cause_id: c for c in kb.get_causes(symptom)}


def _resolve_explanation(
    exp: CauseExplanation,
    kb: KnowledgeBase,
    symptom: str | None,
) -> dict[str, Any]:
    """Resolve KB indices (feel_id, drill_ids) into concrete objects."""
    causes_by_id = _lookup_causes_by_id(kb, symptom)
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
    symptom: str | None,
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
    appear only when populated. ``symptom`` is serialized as ``null``
    for general-mode jobs.
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

# Chunk size for streaming video responses. 1 MB balances round-trip
# count against memory-per-request. Larger is fine for local dev;
# smaller (256 KB) would be politer for constrained hosts like HF
# Spaces. Do not push above ~4 MB — some clients time out on any
# single chunk larger than that.
_VIDEO_CHUNK_SIZE = 1024 * 1024

# Regex-ish parser for the Range header. Accepts:
#   bytes=0-           → suffix open-ended
#   bytes=1024-2047    → both ends
#   bytes=-500         → last 500 bytes
# Multi-range requests (bytes=0-99,200-299) are rejected — video
# players don't use them and supporting multipart/byteranges here
# would be gratuitous complexity.
def _parse_range(header: str, file_size: int) -> tuple[int, int] | None:
    """Parse an HTTP Range header. Returns ``(start, end)`` inclusive
    byte offsets, or ``None`` if the header is malformed or requests
    a multi-range read."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):]
    if "," in spec:
        return None  # multi-range not supported
    try:
        start_s, end_s = spec.split("-", 1)
    except ValueError:
        return None
    try:
        if start_s == "":
            # Suffix range: last N bytes.
            length = int(end_s)
            if length <= 0:
                return None
            start = max(0, file_size - length)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return None
    if start < 0 or start >= file_size or end < start:
        return None
    end = min(end, file_size - 1)
    return start, end


@app.get("/jobs/{job_id}/videos/{filename}")
async def get_job_video(
    job_id: str,
    filename: str,
    request: Request,
):
    """Serve an annotated video for a completed job.

    Handles HTTP Range requests properly (``<video>`` elements always
    send ``Range: bytes=0-`` on the first byte, so full-file
    responses via ``FileResponse`` don't work with Safari/Chrome
    media players). Streams the requested byte range as a chunked
    ``206 Partial Content`` response; falls back to a normal ``200``
    when no Range header is present.

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

    file_size = candidate.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")

    # No Range header → serve the full file. Some clients (curl,
    # wget) do this; browsers don't for media.
    if range_header is None:
        def iter_full():
            with candidate.open("rb") as f:
                while True:
                    chunk = f.read(_VIDEO_CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            iter_full(),
            status_code=200,
            media_type="video/mp4",
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            },
        )

    parsed = _parse_range(range_header, file_size)
    if parsed is None:
        # Malformed or unsatisfiable — RFC 7233 says 416.
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    start, end = parsed
    length = end - start + 1

    def iter_range():
        with candidate.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(_VIDEO_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        iter_range(),
        status_code=206,
        media_type="video/mp4",
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
        },
    )


# ----------------------------------------------------------------------
# Browser routes (HTML)
# ----------------------------------------------------------------------

def _render_context(job: Job, kb: KnowledgeBase) -> dict[str, Any]:
    """Build the Jinja context for a job's HTML rendering.

    Uses ``_serialize_job`` as the single source of truth for
    display data, then adds template-specific derived fields
    (mode label, in-flight flag) so templates stay declarative.
    """
    serialized = _serialize_job(job, kb)
    return {
        "job": serialized,
        "is_general_mode": serialized["symptom"] is None,
        "mode_label": (
            "General analysis"
            if serialized["symptom"] is None
            else f"Symptom: {serialized['symptom']}"
        ),
        "is_terminal": serialized["state"] in ("done", "failed"),
        "is_done": serialized["state"] == "done",
        "is_failed": serialized["state"] == "failed",
    }


@app.get("/app", response_class=HTMLResponse)
async def upload_page(request: Request) -> HTMLResponse:
    """Upload page. Symptom dropdown + handedness toggle + video upload."""
    kb: KnowledgeBase = request.app.state.kb
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "loaded_symptoms": sorted(kb.loaded_symptoms()),
            "max_videos": MAX_VIDEOS,
            "max_file_mb": MAX_FILE_BYTES // (1024 * 1024),
            "max_total_mb": MAX_TOTAL_BYTES // (1024 * 1024),
            "max_context_chars": MAX_CONTEXT_CHARS,
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        },
    )


@app.get("/app/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(job_id: str, request: Request) -> HTMLResponse:
    """Result page. Shareable URL that renders whatever state the job is in.

    In-flight (queued / processing): renders a shell with a spinner
    and injects the job_id for JS polling. Terminal (done / failed):
    renders the full result inline; no polling needed.
    """
    store: JobStore = request.app.state.job_store
    kb: KnowledgeBase = request.app.state.kb
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return templates.TemplateResponse(
        request, "job.html", _render_context(job, kb),
    )


@app.get("/app/jobs/{job_id}/partial", response_class=HTMLResponse)
async def job_partial(job_id: str, request: Request) -> HTMLResponse:
    """Result fragment. Called by JS when polling sees a terminal state.

    Returns just the ``#result-region`` inner HTML — the client swaps
    it into the page without a full reload. Same Jinja partial the
    full page uses, so rendering stays in one place.
    """
    store: JobStore = request.app.state.job_store
    kb: KnowledgeBase = request.app.state.kb
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return templates.TemplateResponse(
        request, "partials/result.html", _render_context(job, kb),
    )