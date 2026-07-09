# Phase 5 Notes

Running notes on Phase 5 work: turning Phases 1–4 into a reachable
web app. Complements `phase1_notes.md`, `phase2_notes.md`,
`phase3_notes.md`, `phase4_notes.md`, and `phase5_1_general_analysis.md`
(which covers the symptom-optional path in depth and is not
duplicated here).

## Phase 5 goal

Given the end-to-end analysis pipeline built in Phase 4
(`analyze_swings`), stand up an HTTP interface a user can actually
reach: upload videos through a browser, wait through the analysis,
receive a rendered diagnosis with pose-overlay videos alongside.
Two constraints shaped every architectural choice — a 35–60 second
analysis pipeline (can't hold an HTTP connection open that long on
any realistic host), and the v1 portfolio scope (no framework
heroics, no premature scaling infrastructure).

## What was built

- **FastAPI async job architecture** (`api/jobs.py`, `api/main.py`) —
  four JSON endpoints backing the browser flow, plus a Semaphore(1)-
  serialized background pipeline runner and a per-session filesystem
  scratchpad.
- **Browser frontend** (Jinja2 templates + vanilla JS in
  `api/templates/`, `api/static/`) — two pages, `/app` and
  `/app/jobs/{id}`, with polling-driven live updates on the result
  page.
- **Video serving with Range support + H.264 transcode** — the two
  video-related sagas that Delivery 2 spent most of its debug budget
  on. Documented in detail below.
- **Symptom-optional path** — covered separately in
  `phase5_1_general_analysis.md`. Backend implications
  (`symptom: str | None` threaded through the pipeline chain) are
  captured there; the FastAPI form normalization from empty-string
  to `None` is the only Phase 5 addition.

---

## Locked-in design decisions

Eleven decisions established in Phase 5 that constrain future work.
These are not to be relitigated without new evidence.

### 1. Two-endpoint async job design

`POST /analyze` accepts uploads, creates a job, spawns background
processing, and returns immediately with a job ID. `GET /jobs/{id}`
is polled by the client until state hits `done` or `failed`. No
streaming, no WebSockets, no server-sent events.

Constraint that forced this: the analysis pipeline takes 35–60
seconds for 3–5 swings. Hugging Face Spaces (the intended
deployment target) enforces a request timeout well below that;
even hosts without an explicit timeout make holding a connection
open for a minute a bad citizen. Streaming responses solve the
timeout half but complicate the client (parse partial JSON, handle
mid-stream failure), and the polling client is straightforward.

Cadence: 2s poll interval on the client. Server produces cheap
JSON; the round-trip is <20ms locally, so the load impact is
negligible even for many concurrent users. Elapsed counter on the
client ticks independently at 1s so it feels live between polls.

### 2. In-memory JobStore, not Redis or a database

`JobStore` holds jobs in a plain `dict` guarded by an `asyncio.Lock`.
No persistence. Trade-off accepted: jobs die on server restart, and
horizontal scaling would require a state layer. Neither matters for
v1 — the deployment target is a single container on a free tier,
users don't come back to check yesterday's result, and the whole
project has zero uptime requirement.

Documented as an intentional constraint rather than a limitation to
fix. If v2 adds user accounts and session history, that's the point
to swap in real storage.

### 3. Task references held in a set to prevent GC

`JobStore.spawn` creates a task via `asyncio.create_task(...)` and
adds it to a module-level set. The task's `done` callback removes
itself. Without this, Python's garbage collector can (and
occasionally will) collect the coroutine while it's still running,
killing the pipeline mid-flight with an inscrutable error.

Standard asyncio idiom, easy to miss. Documented so a future
refactor doesn't drop this "unused" set.

### 4. Semaphore(1) serializing pipeline execution

Every background pipeline run acquires a `Semaphore(1)` before
starting. Effect: at most one pipeline is running at a time,
regardless of how many jobs are queued.

Rationale: MediaPipe and OpenCV are not thread-safe in obvious
ways, and the pipeline is CPU-bound. Running two in parallel on a
single-worker deployment would just contend for the same CPU
without finishing either faster, and creates a real risk of
MediaPipe internal-state corruption. Serializing is simpler and
gives predictable latency: "your job is queued behind N others"
is easier to communicate than "your job is running slowly because
two others are also running slowly."

For a real product this becomes a queue with workers. For v1 it's
one line.

### 5. Index-based filenames on disk

Uploads are saved as `swing_01.mov`, `swing_02.mov`, etc. — the
original filename from the multipart form is never used. Purely a
safety move: original filenames are untrusted user input, and
using them on the filesystem opens both traversal risk (`../../etc/passwd`)
and encoding-collision headaches on cross-platform paths.

The pipeline doesn't need the original name for anything, so
throwing it away costs nothing.

### 6. Session rollback via `store.abort()` on validation failures

When streaming uploads to disk, we enforce two caps: 100 MB per
file, 500 MB total. Both are checked byte-by-byte during streaming
(not from `Content-Length` headers, which can lie). If either cap
is exceeded mid-stream — say, during file 3 of 5 — the partial file
is deleted, but at that point files 1 and 2 are already on disk in
a session directory.

`store.abort(job)` handles the cleanup: deletes the entire session
dir and removes the job from the store. Alternative would be
letting the periodic cleanup task handle it later (1h TTL), but
that leaves partial state around for the next 15-minute cleanup
tick. Explicit abort is a small block of code and closes the loop
cleanly.

### 7. Path traversal defense via `relative_to()`

`GET /jobs/{id}/videos/{filename}` accepts an arbitrary filename in
the URL. Standard defense: resolve the candidate path against the
session's annotated directory, then call `candidate.relative_to(annotated_dir)`.
If that raises `ValueError`, the candidate escaped the intended
directory; return 404.

Small detail, but the class of bug it prevents (`filename=..%2F..%2Fetc%2Fpasswd`)
is well-known and worth documenting the fix pattern.

### 8. HTTP Range request handling for video serving

This is the first Delivery 2 saga. `<video>` elements in Chrome and
Safari always send `Range: bytes=0-` on the initial request,
expecting a `206 Partial Content` response. FastAPI's built-in
`FileResponse` acknowledges the Range request with a 206 but
returns only a stub body (~300 bytes) instead of the requested
range. Chrome interprets that as "content received" and shows a
black player without any visible error.

Fix: implement Range parsing and streaming manually in
`get_job_video`. Parses `bytes=N-M` (and `bytes=N-`, and `bytes=-N`
suffix form); rejects multi-range requests (video players don't use
them); streams the file in 1 MB chunks with the appropriate
`Content-Range` and `Content-Length` headers. Falls back to a
normal 200 when no Range header is present (curl, wget).

Standard HTTP; nothing exotic. The reason it took a debug session
to isolate was that the failure mode is silent — no exception, no
warning, just a black player.

### 9. H.264 transcode via ffmpeg after visualizer

Second Delivery 2 saga. OpenCV's `VideoWriter` on macOS writes
MPEG-4 Part 2 with FourCC `mp4v` — a container format valid enough
that QuickTime plays it (macOS system codecs handle Part 2), but
browsers only decode H.264 inside MP4. Chrome and Safari showed
black players even after the Range fix.

Additionally, OpenCV places the `moov` atom at the end of the file
by default. Browsers need `moov` at the start to begin playback
without a full download, or they seek to the tail probing for
metadata, get confused, and give up.

Fix: post-process each annotated video with ffmpeg after
`render_segmented_pose_video` writes it. One pass transcodes to
H.264 baseline profile (maximum browser compatibility including
old mobile Safari), sets pixel format to yuv420p, and moves `moov`
to the start via `-movflags +faststart`. Adds ~2–3 seconds per
video; acceptable trade.

ffmpeg is a real deployment dependency now. The helper
(`_make_browser_compatible` in `pipeline.py`) fails gracefully with
a loud warning if ffmpeg isn't on PATH — the video still works in
curl and QuickTime, only browser playback breaks. Documented in
the pipeline docstring; the HF Spaces Dockerfile will need to
install ffmpeg.

Two things worth capturing about this failure:
- The Range bug and the codec bug looked identical from the browser
  side (black player, no error). Testing them in isolation missed
  the interaction — a QuickTime-plays-fine file with a Range-serving
  bug looks identical to a Range-serving-fine file with a
  browser-incompatible codec.
- The FourCC issue is silent. `cv2.VideoWriter_fourcc(*"mp4v")`
  succeeds on macOS with no warning; there's no "your file is
  browser-incompatible" signal anywhere in the OpenCV API. The only
  way to catch this is `ffprobe` or browser testing.

### 10. KB and Anthropic client injected via lifespan, not per-request

`app.state.kb` and `app.state.anthropic_client` are populated once
during FastAPI's lifespan startup and injected into every request
handler via `request.app.state`. Same pattern as `analyze_swings`
accepting `client` and `kb` parameters — dependency injection at
every layer.

Rationale: KB loading involves Pydantic validation over 9 YAML
files plus the baseline; doing it per-request would add ~50ms
overhead and, more importantly, would mean a KB validation failure
at file-edit time would only surface on the next request rather
than at server startup. The startup-fails-loud pattern is worth
the small structural cost.

### 11. Two-page frontend, server-rendered with progressive-enhancement partial

Two pages: `/app` (upload form) and `/app/jobs/{id}` (result). No
single-page app framework. Server renders both fully at request
time; JS layers on interactive behavior (file-list state,
polling, live tab title updates, copy-to-clipboard).

The polling-completion flow uses a small progressive-enhancement
pattern: `GET /app/jobs/{id}/partial` returns just the result
region's HTML fragment, not a full page. When JS detects the job
reached a terminal state, it fetches the partial and swaps it into
the DOM without a full page reload. This keeps rendering logic in
one place (the `partials/result.html` Jinja template is used both
by the full page and the partial endpoint) — server-rendered from
one source of truth, no duplicate render paths.

Alternative would have been fully client-side rendering. Rejected
because it means every render path has two implementations (Jinja
+ JS), which drifts over time. Server-side rendering with a small
JS layer keeps the codebase honest.

---

## Empirical findings during Phase 5

### Both video bugs looked identical from Chrome's side

Worth pulling out as a standalone lesson: the Range-header bug and
the FourCC bug produced the exact same visible symptom — a
`<video>` element that renders as a black rectangle with a play
button and no error. Both required getting into Chrome's Network
tab and inspecting Range headers to distinguish them, and even
then the first pass on the Range fix looked "successful" (206
responses appeared, byte counts looked plausible) but the video
still didn't play because the codec was also wrong.

Lesson for future browser-facing work: when a video won't play,
verify (1) curl can download the full file, (2) ffprobe reports a
browser-compatible codec (`codec_name=h264`, not `mpeg4`), (3) the
file plays in browsers other than the one showing the problem, and
(4) the browser is actually requesting the whole file, not just
the tail. Any one of those breaking is a distinct failure mode.

### General-mode ranking pool includes causes across every symptom

Confirmed in production during `test_api.py`'s general-mode case:
uploading swing_16 alone with no symptom produced
`cupped_lead_wrist_at_top` at 1.40 (the same top result as
symptom-mode), plus `insufficient_body_rotation` at 0.5 as
secondary — the second cause lives in `lack_of_distance.yaml` but
scored against pooled causes regardless. Confirms the
`collect_unique_causes` pooling logic is doing what it says, and
that general-mode surfaces observations symptom-mode would never
show a user (`insufficient_body_rotation` at 0.5 wouldn't clear the
symptom-scoped `slice` KB).

### Session-directory cleanup timing

The periodic cleanup task runs every 15 minutes and deletes jobs
that hit a terminal state more than 1 hour ago. Real-user
implication: the shareable link on the result page is honestly
labeled "This URL stays live for 1 hour" and that's a load-bearing
promise, not decoration. Longer-term retention would require the
persistent-storage decision (item 2 above).

### FastAPI's `TemplateResponse` signature changed

Starlette's newer `TemplateResponse` takes `request` as the first
positional argument, separate from the context dict. The older
form (context dict with `"request"` key inside it) still parses
but hits a confusing "unhashable type: dict" error deep in Jinja's
cache layer when the argument-detection heuristic picks the wrong
signature. Documented in the route handlers with the correct call
pattern; if a future FastAPI upgrade breaks something, this is a
plausible candidate.

---

## Visual design direction

Full context in the delivery discussion; captured here so it lives
in the repo docs.

Target aesthetic: editorial-precise. Closer to Stripe docs or
Linear or a physical-therapist post-visit report than any golf
app. The visual work is done by typography, whitespace, and
restraint — not by color, gradients, or decoration. Reference
points that landed useful: Athletic Motion Golf's serious-coaching
tone (professional, uncluttered, data-forward, treats the user as
intelligent); WHOOP's design philosophy ("the coaching IS the
data" — don't split diagnosis and recommendation across separate
screens); editorial magazines' typography (serif contrast for
emphasis, restrained sans for chrome).

Specific moves:

- **Warm off-white paper background** (`#faf8f4`) rather than
  clinical white. Slight warmth reads as considered, not sterile.
- **Deep navy accent** (`#24405c`) rather than the sports-app forest
  green a golf app is tempted to reach for.
- **Feel block as magazine pull-quote**. Serif Georgia at 26px,
  left-rule instead of full-box border, italic byline for the
  "why it works" note. The feel is the emotional center of the
  diagnosis; the visual weight makes that legible.
- **Setup badge visually distinct from swing badge**. Setup gets a
  gold outlined ring; swing gets a muted filled pill. Reinforces
  "check setup issues first before changing your swing" at a glance.
- **CTAs de-escalated**. "Analyze another swing" on the result page
  is a text arrow link, not another blue button. Preserves the
  hierarchy where the upload page's Analyze button is the primary
  action.
- **Editorial spacing**. 4/8/12/16/24/32/48 rhythm rather than ad
  hoc values.

Explicitly rejected:

- Dark theme (WHOOP's context is 24/7 biometric monitoring; ours is
  reading a diagnosis at a driving range in daylight)
- Background patterns or geometric decoration (the calm surface IS
  the design; adding pattern would push into "tacky" territory
  that the direction was chosen to avoid)
- Achievement or gamification styling (star ratings, badges, "level
  up" language — every existing golf app does this; opting out is a
  point of distinction)
- Sports-app color intensity (bright greens, saturated reds)

---

## Deferred to Phase 5+ (real-user data)

- **Real-user testing** (v1 success criterion #2: five golfers,
  three of whom recognize something a coach told them).
- **Threshold retuning against real-user data**. Every numeric
  threshold in `kb/` was tuned from Jonathan's 15-swing baseline plus
  fault demos. Real users will inevitably shift what values are
  appropriate. Already flagged in `phase3_notes.md` as a Phase 5+
  concern; noting again here because it becomes actionable once
  the tool is public.
- **Fallback-rate calibration for pull/push symptoms**. Predicted in
  `phase4_notes.md` to fall back more often than other symptoms
  because they each lost two causes to the invisible-axis principle.
  Real-user data will confirm or refute.

## Deferred to v2

See `docs/v2_priorities.md` for the full list. The single
highest-impact v2 change remains **face-on camera view** — restores
five dropped KB causes and returns three swapped-to-fallback causes
to their proper primary indicators. Phase 5's honest "the tool
can't see grip / alignment / weight from this angle" disclosure
lives in the result page footer and is a load-bearing piece of
v1 copy; it becomes removable in v2.

Other v2 items relevant to Phase 5 specifically:

- **Persistent job storage** if longitudinal tracking becomes a
  priority (Phase 5 v2 candidate #5 in `v2_priorities.md`).
- **Auth and user accounts** for the same purpose. v1 stateless
  design is deliberate; v2 changes only if there's a real need.

---

## Cross-references

- `phase5_1_general_analysis.md` — symptom-optional path
  architecture and empirical findings for general mode.
- `module_interfaces.md` — public API signatures for every module
  Phase 5 touches (updated during this phase for the `symptom: str | None`
  type change across matcher, output_schema, llm_client, prompt,
  and pipeline).
- `v2_priorities.md` — deferred work, ranked by impact.


## Deployment findings (Fly.io, July 2026)

Deployed to Fly.io shared-cpu-1x with 1GB RAM. Findings that
matter for anyone reading this repo cold:

**Single-machine, always-on configuration.** The default
`auto_stop_machines = 'stop'` with 2 machines produced 404s
during polling — uploads landed on Machine A but polls sometimes
routed to Machine B, which had no in-memory record of the job.
Fixed with `min_machines_running = 1` and
`auto_stop_machines = 'off'` in `fly.toml` plus
`fly scale count 1`. Documented as v2 item #6.

**MediaPipe model pre-download at Docker build time.** MediaPipe
lazily downloads pose models into its own `site-packages`
directory on first use. When the container runs as UID 1000
(HF Spaces convention, also Fly.io default), the write fails
with a permission error. Fix: run all three model complexities
during `docker build` while still root, so the files exist
before user switch. Adds ~30s to build time and 20MB to image
size; worth it for reliable cold starts.

**H.264 transcode required for browser video playback.** OpenCV
VideoWriter defaults to mp4v (MPEG-4 Part 2 on macOS). QuickTime
plays these via system codecs; browsers cannot decode them.
Fix: ffmpeg post-process step in `pipeline.py::_make_browser_compatible`
converts to H.264 baseline + yuv420p + moov-atom-at-start.
This is why `ffmpeg` is a real deployment dependency, not a dev tool.

**Deploy image size: 550 MB.** Dominated by MediaPipe (~200 MB),
OpenCV headless (~90 MB), and Python base image (~130 MB).
Acceptable for shared-CPU Fly deployment; would be worth
optimizing for larger fleets.

**Realistic cost, 20-50 analyses/month:** $1-2/month Fly +
$0.40-1.00/month Anthropic API = $1.50-3.00/month total.
Coffee money for a live portfolio piece.