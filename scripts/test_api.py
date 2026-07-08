"""End-to-end sanity script for the Phase 5 API.

Assumes the API is already running (``uvicorn golf_diagnostic.api.main:app``)
and that ``data/raw/swing_16.mov`` exists. Uses stdlib only —
``urllib`` for HTTP, ``mimetypes`` for detection, ``uuid`` for the
multipart boundary — so nothing new needs to be added to
requirements.

Run::

    python scripts/test_api.py

What it does:

1. ``GET /`` — verify server is up, KB loaded, Anthropic ready.
2. ``POST /analyze`` (negative) — unsupported symptom rejected 400.
3. ``POST /analyze`` (negative) — bad extension rejected 400.
4. ``POST /analyze`` (positive) — swing_16 + symptom=slice.
5. Poll ``GET /jobs/{id}`` until ``done`` or ``failed``.
6. Print the diagnosis and confirm annotated video URLs resolve.

Expected outcome on the positive path: state transitions
``queued`` → ``processing`` → ``done``, with a primary cause of
``cupped_lead_wrist_at_top`` (validated on swing_16 during Phase 4).

Cost: ~$0.01 (one Anthropic call, cached prompt).
"""

from __future__ import annotations

import io
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE_URL = "http://localhost:8000"
SWING_PATH = Path("data/raw/swing_16.mov")
POLL_INTERVAL = 2.0        # seconds
POLL_TIMEOUT = 180.0       # 3 minutes — analyze_swings on 1 clip is ~15-30s


# ----------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ----------------------------------------------------------------------

def _get(path: str) -> tuple[int, dict | None, str]:
    """GET a URL. Handles binary responses (annotated videos) safely.

    Returns ``(status, parsed_json_or_None, text_or_placeholder)``.
    Non-UTF-8 bodies and non-JSON UTF-8 bodies both return
    ``data=None`` without raising — callers that only care about
    status still work.
    """
    url = BASE_URL + path
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read()
            try:
                text = raw.decode("utf-8")
                data = json.loads(text) if text else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                text = f"<{len(raw)} bytes of binary data>"
                data = None
            return resp.status, data, text
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except Exception:
            data = None
        return e.code, data, body


def _post_multipart(
    path: str,
    files: list[tuple[str, Path]],
    fields: dict[str, str],
) -> tuple[int, dict | None, str]:
    """POST a multipart/form-data request with files + fields."""
    boundary = f"----boundary-{uuid.uuid4().hex}"
    buf = io.BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        buf.write(value.encode("utf-8"))
        buf.write(b"\r\n")
    for name, filepath in files:
        filename = filepath.name
        content_type, _ = mimetypes.guess_type(str(filepath))
        content_type = content_type or "application/octet-stream"
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        buf.write(f"Content-Type: {content_type}\r\n\r\n".encode())
        buf.write(filepath.read_bytes())
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    body = buf.getvalue()

    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body_out = resp.read().decode("utf-8")
            data = json.loads(body_out) if body_out else None
            return resp.status, data, body_out
    except urllib.error.HTTPError as e:
        body_out = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body_out)
        except Exception:
            data = None
        return e.code, data, body_out


# ----------------------------------------------------------------------
# Assertions
# ----------------------------------------------------------------------

def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)
    sys.exit(1)


def check(cond: bool, msg: str) -> None:
    if cond:
        ok(msg)
    else:
        fail(msg)


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

def test_health() -> None:
    print("\n[1] GET /")
    status, data, _ = _get("/")
    check(status == 200, f"status is 200 (got {status})")
    check(data is not None, "response is JSON")
    check(data.get("status") == "ok", "status == 'ok'")
    check(
        isinstance(data.get("loaded_symptoms"), list)
        and len(data["loaded_symptoms"]) == 9,
        f"9 symptoms loaded (got {len(data.get('loaded_symptoms') or [])})",
    )
    check(data.get("anthropic_client_ready") is True, "anthropic client ready")
    limits = data.get("upload_limits") or {}
    check("max_file_bytes" in limits, "upload_limits present")


def test_reject_unsupported_symptom() -> None:
    print("\n[2] POST /analyze — unsupported symptom (expect 400)")
    if not SWING_PATH.exists():
        print(f"  (skipped: {SWING_PATH} not found)")
        return
    status, data, _ = _post_multipart(
        "/analyze",
        files=[("videos", SWING_PATH)],
        fields={"symptom": "not_a_real_symptom"},
    )
    check(status == 400, f"status is 400 (got {status})")
    detail = (data or {}).get("detail") or []
    joined = " | ".join(detail) if isinstance(detail, list) else str(detail)
    check(
        "Unsupported symptom" in joined,
        f"error mentions 'Unsupported symptom' (got: {joined!r})",
    )


def test_reject_bad_extension(tmp_dir: Path) -> None:
    print("\n[3] POST /analyze — bad extension (expect 400)")
    fake = tmp_dir / "not_a_video.txt"
    fake.write_bytes(b"not a video")
    status, data, _ = _post_multipart(
        "/analyze",
        files=[("videos", fake)],
        fields={"symptom": "slice"},
    )
    check(status == 400, f"status is 400 (got {status})")
    detail = (data or {}).get("detail") or []
    joined = " | ".join(detail) if isinstance(detail, list) else str(detail)
    check(
        "unsupported extension" in joined.lower(),
        f"error mentions unsupported extension (got: {joined!r})",
    )


def test_analyze_swing_16() -> str:
    print("\n[4] POST /analyze — swing_16 + symptom=slice")
    if not SWING_PATH.exists():
        fail(f"{SWING_PATH} not found; run from project root")
    status, data, _ = _post_multipart(
        "/analyze",
        files=[("videos", SWING_PATH)],
        fields={"symptom": "slice"},
    )
    check(status == 200, f"status is 200 (got {status})")
    check(isinstance(data, dict) and "job_id" in data, "response has job_id")
    check(data.get("state") == "queued", f"initial state is 'queued' (got {data.get('state')!r})")
    print(f"  → job_id: {data['job_id']}")
    return data["job_id"]


def test_poll_until_done(job_id: str) -> dict:
    print(f"\n[5] Poll GET /jobs/{job_id} until terminal state")
    start = time.time()
    last_state = None
    while True:
        elapsed = time.time() - start
        if elapsed > POLL_TIMEOUT:
            fail(f"timed out after {POLL_TIMEOUT}s (last state: {last_state})")
        status, data, _ = _get(f"/jobs/{job_id}")
        check(status == 200, f"status is 200 (got {status})")
        state = (data or {}).get("state")
        if state != last_state:
            print(f"  [{elapsed:5.1f}s] state → {state}")
            last_state = state
        if state == "done":
            ok(f"reached 'done' in {elapsed:.1f}s")
            return data
        if state == "failed":
            fail(f"job failed: {(data or {}).get('error')}")
        time.sleep(POLL_INTERVAL)


def test_diagnosis_shape(payload: dict, job_id: str) -> None:
    print("\n[6] Result shape + annotated video reachable")
    result = payload.get("result") or {}
    diagnosis = result.get("diagnosis") or {}
    check("summary" in diagnosis, "diagnosis.summary present")
    check(diagnosis.get("summary"), "diagnosis.summary non-empty")

    # In diagnosis mode we expect primary populated and no fallback message.
    # In fallback mode the reverse. Print which and inspect either way.
    primary = diagnosis.get("primary")
    fallback = diagnosis.get("fallback_message")
    if primary is not None:
        ok("primary cause populated (diagnosis mode)")
        print(f"    cause_id: {primary.get('cause_id')}")
        print(f"    feel:     {(primary.get('feel') or {}).get('text')!r}")
        check("technical_explanation" in primary, "primary.technical_explanation present")
        check("feel" in primary, "primary.feel present")
    elif fallback is not None:
        ok("fallback_message populated (fallback mode)")
        print(f"    message preview: {fallback[:120]}...")
    else:
        fail("neither primary nor fallback_message populated")

    # Annotated videos: URLs should be reachable.
    urls = result.get("annotated_video_urls") or []
    check(len(urls) >= 1, f"at least one annotated video URL (got {len(urls)})")
    first_url = urls[0]
    status, _, _ = _get(first_url)
    check(status == 200, f"annotated video {first_url} is reachable (got {status})")

    # Debug trail
    ranked = result.get("top_ranked_causes") or []
    if ranked:
        print(f"  top ranked (debug):")
        for rc in ranked[:5]:
            print(f"    {rc.get('score', 0):.2f}  {rc.get('cause_id')}")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> None:
    tmp_dir = Path("/tmp/test_api_scratch")
    tmp_dir.mkdir(exist_ok=True)

    test_health()
    test_reject_unsupported_symptom()
    test_reject_bad_extension(tmp_dir)
    job_id = test_analyze_swing_16()
    payload = test_poll_until_done(job_id)
    test_diagnosis_shape(payload, job_id)

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()