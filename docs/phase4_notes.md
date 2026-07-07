# Phase 4 Notes

Running notes on Phase 4 work: the LLM diagnostic reasoning layer
and the end-to-end analysis pipeline. Complements
`phase1_notes.md`, `phase2_notes.md`, and `phase3_notes.md`.

## Phase 4 goal

Given the matcher's `list[RankedCause]` output, produce coaching-
quality prose the user can read: technical explanation citing the
user's actual feature values, one selected feel from the KB, and
zero-to-two drill references. Handle the fallback branch cleanly
when nothing clears the diagnostic threshold. Then compose all
layers (pose → segmentation → features → matcher → LLM) into a
single `analyze_swings()` entry point that Phase 5's FastAPI route
will wrap.

Built:
- `src/golf_diagnostic/diagnosis/output_schema.py` — Pydantic models
  for the LLM's structured output, plus `validate_against_kb()`
- `src/golf_diagnostic/diagnosis/prompt.py` — system prompt, user
  message construction, tool schema derivation, mode branching
- `src/golf_diagnostic/diagnosis/llm_client.py` — Anthropic API
  wrapper with retry-on-validation-failure
- `src/golf_diagnostic/pipeline.py` — full end-to-end
  `analyze_swings()` orchestration
- Six new sanity scripts: `test_output_schema.py`, `test_prompt.py`,
  `test_diagnosis.py`, `test_pipeline.py` (plus updates to
  existing scripts to accommodate new imports)

Phase 4 exit criterion met.

---

## Locked-in design decisions

Ten design decisions established in Phase 4 that constrain Phase 5+
work. These are not to be relitigated without new evidence.

### 1. Structured output via Anthropic tool-use, not JSON prompting

The LLM emits its response by calling a single `emit_diagnosis` tool
whose input schema is generated from `DiagnosticOutput.model_json_schema()`.
`tool_choice={"type": "tool", "name": "emit_diagnosis"}` forces the
call; no plain-text output is possible.

Why not JSON-in-prose: tool-use gives the LLM a machine-readable
schema (including our Field descriptions), and Anthropic's SDK
returns tool_use blocks that parse cleanly with Pydantic. No regex,
no "extract the JSON from between the backticks" fragility. Same
pattern as `kb/loader.py`'s YAML → Pydantic contract, applied to
LLM output.

### 2. Feel selection by index, not by regenerated text

The LLM emits `feel_id: int` — an index into the KB cause's `feels`
list. The frontend renders the feel text verbatim from the KB.

Why not have the LLM restate the feel: golf feels are sensitive to
specific wording. "Feel like the back of your lead hand points at
the ground" is deliberately blunt and visual; if the LLM paraphrases
it to something softer, the imagery loses force. The KB is
authoritative for feel text; the LLM only picks. Same rationale for
`drill_ids` as indices.

### 3. Two-phase validation (structural + semantic)

Pydantic handles structural validation at parse time (field types,
`min_length`, `max_length`, mutually-exclusive-path validator).
`validate_against_kb()` handles KB-aware semantic validation:
- `cause_id` must be in the ranked list passed to the LLM
- `feel_id` must be a valid index for that cause's feels list
- `drill_ids` must be valid indices for that cause's drills list
- Same `cause_id` not cited more than once across primary + secondary

Together they form the anti-hallucination boundary. Same load-time-
validation pattern as `kb/loader.py`, applied to LLM output.

### 4. Retry once on validation failure via tool_result/is_error

When either validation layer fails, the retry conversation:
1. Echoes the LLM's malformed `tool_use` back as an assistant turn
2. Sends a user turn containing a `tool_result` block with the
   validation error and `is_error: True`
3. Re-forces `tool_choice` so the LLM must retry

Uses the semantically correct Anthropic tool-use protocol rather
than a plain-text "your response was invalid" message. `max_retries=1`
by default: one shot to self-correct, then raise loud. Looping is
worse than surfacing the bug.

### 5. Mode auto-detection in `llm_client.py`, not in `build_prompt`

`generate_diagnosis()` calls `should_fall_back(ranked)` and passes
`mode="diagnosis"` or `mode="fallback"` to `build_prompt()`.
`build_prompt` is a pure function of its inputs — no side effects,
no branching on state. This makes it easy to unit test the prompt
shape (as `test_prompt.py` does with fixtures) while `llm_client.py`
handles the API mechanics.

### 6. `build_prompt` raises `ValueError` if mode disagrees with input

Concretely: `mode="diagnosis"` with no cause clearing the floor
raises. This can't happen if the caller went through
`generate_diagnosis` (which auto-detects mode), but if a caller
misuses `build_prompt` directly, the invariant surfaces immediately
rather than sending the LLM a contradictory prompt ("produce a
diagnosis" + empty ranked list).

### 7. Prompt caching on system prompt AND tool schema

Both `system` blocks and `tools` are marked
`cache_control: {"type": "ephemeral"}`. The system prompt (~5300
chars) and tool schema (~5-6K tokens together) are cache-stable
across every call — only the user message varies per call.

Empirical result: Case B of `test_pipeline.py` shows
`cache_read_input_tokens=2507` on the second call after Case A's
`cache_creation_input_tokens=2507`. Cache hit works as designed.
Effective per-call cost with cache hit: ~$0.011 for a typical
diagnosis (down from ~$0.022 uncached). Matches the spec estimate.

### 8. LLM sees description + matched indicators + user context

Deliberately withheld from the LLM's view:
- The KB indicator's `reasoning` field (contains internal engineering
  notes like "stopgap indicator", "threshold set from Phase 2 audit")
- The KB cause's `fix.technical_instruction` (frontend renders this
  directly from the KB — LLM doesn't get to rephrase it)
- Baseline mean/stddev as separate numbers (embedded in the
  reconstructed raw value + "N stddevs above baseline" phrasing
  instead)
- Sub-floor causes (in diagnosis mode) or unranked causes
  (in either mode)

This prevents the LLM from either (a) leaking engineering language
into user output, (b) paraphrasing carefully-authored KB text, or
(c) inventing/citing causes outside the ranked list.

### 9. Voice guidance: cite coaching units, describe proxies qualitatively

The system prompt distinguishes two kinds of values the LLM might
encounter:
- Real coaching units (degrees, seconds): cite the number directly.
  "Your trail wrist was extended 52° at the top of the backswing."
- Proxy / normalized values (`*_proxy`, `*_target_axis`,
  `*_displacement`, `*_vertical_change`): describe the pattern
  qualitatively. "Your shoulders were noticeably more open at
  impact than a typical swing." Never quote z-scores or stddev
  counts to the user.

The indicator lines in the prompt reconstruct raw values from
z-scores using `raw = z * baseline.stddev + baseline.mean`, so
both raw and z-score info are available to the LLM. The LLM decides
which is coaching-appropriate.

Validated empirically: after this change, LLM output dropped
z-score citations ("1.85 z-score") in favor of qualitative
descriptions ("noticeably more open than typical"). Cleaner
coaching tone with no ambiguity.

### 10. `analyze_swings()` returns an `AnalysisResult`, not a bare `DiagnosticOutput`

Return value includes:
- `diagnosis: DiagnosticOutput` — the LLM output (main product)
- `annotated_video_paths: list[Path]` — populated when
  `annotated_output_dir` is set; empty when None
- `ranked_causes: list[RankedCause]` — for debug dashboards and
  Phase 5 observability

Forward-compatible: Phase 5 needs the annotated videos to render
alongside the diagnosis, and `ranked_causes` gives an audit trail
for "why did the LLM say what it said." A bare `DiagnosticOutput`
return would force Phase 5 to bolt on side-channels for these.

---

## Empirical findings from Phase 4 testing

### The z-score annotation trap

Initial `generate_diagnosis` output cited z-scores as if they were
raw measurements: *"Your shoulder rotation at impact registered
1.85 across all four swings"*. The "1.85" is a z-score, not degrees
of rotation.

Root cause: `_format_indicator_line` in `prompt.py` passed
`representative_value` to the LLM unannotated regardless of mode.
For raw-mode indicators (wrist angles in degrees), the value is
directly citable; for zscore-mode indicators (rotation proxies),
the value is a z-score that requires translation.

Fix: reconstruct the mean raw feature value from the z-score using
`raw = z * baseline.stddev + baseline.mean`. Show both raw and
z-score in the prompt line. Update system prompt Voice section to
route the LLM's citation behavior by feature kind (coaching units
→ cite; proxies → qualitative).

Validated on `test_diagnosis.py` re-run: LLM output changed from
"registered 1.85" to "noticeably more open at impact than a typical
swing" for the same underlying indicator.

### KB parameter went from unused to load-bearing

`build_prompt()` originally received `kb` but didn't use it (`noqa:
ARG001`). The z-score fix made `kb.baseline` load-bearing — needed
to reconstruct raw values. This is the good kind of API stability:
callers were already passing kb, so the fix was internal-only.

### Cache dynamics on retry

Retry attempts extend `messages` but keep `system` and `tools`
identical. So even in a two-attempt call, the cache hit still
applies to system + tools on the retry. Cost of a retry is roughly
one uncached input round-trip on the retry-specific messages, not
a full cache-write penalty.

Not empirically verified this phase (no retries fired in any test),
but architecturally sound.

### Pipeline consistency filter works as designed

`test_pipeline.py` Case B: swing_16 (extreme cupped demo) +
swing_09 (a "normal" swing with visible-but-mild cupping). All
scores came back 0.00. The 60% consistency filter suppressed every
indicator that fired on one swing but not the other.

At n=2, the math is `1.2` — a filter of 60% requires ≥1.2 swings,
so 1/2 = 50% fails and only 2/2 = 100% passes. With a fault demo
paired with a mostly-normal swing, few if any indicators fire on
both. Fallback is the correct outcome.

The LLM handled this cleanly: fallback message referenced the
closest candidate ("over-the-top move — your instinct that 'the
ball is going right the moment I start the downswing' is a classic
description of that move"), explained the two-swing limitation, and
called out all four invisible-axis blind spots (grip, alignment,
weight, face-on view). Genuine coaching value in the fallback case,
not a "sorry, no diagnosis" dead end.

### The consistency filter is genuinely conservative on small n

At n=2, an indicator needs to fire on **both** swings.
At n=3, at least **2 of 3** swings (67%).
At n=4, at least **3 of 4** swings (75%).
At n=5, at least **3 of 5** swings (60%).

For real user uploads of 3-5 swings, the design is calibrated to
n=5 (target 60% = 3/5). Smaller uploads are functional but more
prone to fallback — this is a real UX consideration, not a bug.
Phase 5's upload UI should nudge users toward 5 swings and
communicate that lower-N uploads may hit fallback more often.

### Real matcher output is friendly to the prompt code

`test_pipeline.py` Case A: real matcher produced
`trail_wrist_angle_at_P4=51.96, lead_wrist_angle_at_P4=86.58` from
swing_16's cached pose. The prompt code (which was validated with
fixtures in `test_prompt.py`) accepted real matcher output with no
adjustment. No schema drift between fixture assumptions and real
matcher output — the RankedCause / MatchedIndicator interface is
stable.

### Sonnet 4.6 handles our workload well

Every LLM call in Phase 4 testing passed validation on the first
attempt. No retries fired. Token usage per call:
- Uncached first call: ~2500 in / 300-600 out
- Cached subsequent call: ~1500-1700 in (of which ~2500 cached) /
  300-600 out
- Effective cost: ~$0.010-$0.022 per call

The tool-use pattern with forced choice is well-supported. Field
descriptions in the Pydantic model are respected — the LLM does
what the schema says without hand-holding.

---

## What Phase 4 does NOT cover

### Retry path not exercised on live API

The retry logic in `llm_client.py` was designed and code-reviewed
but never fired during Phase 4 testing — the LLM's first attempt
always passed validation. The mechanism (tool_result with
is_error=True → follow-up API call) is standard Anthropic protocol
and code-inspected, but not empirically validated on this project.

If Phase 5 sees genuine retry cases (e.g., LLM emitting an unknown
`cause_id` under some prompt drift), they'll surface then and can
be inspected against the retry logic.

### Only slice symptom tested end-to-end

`test_pipeline.py` and `test_diagnosis.py` both exercise the slice
symptom. The remaining 8 symptoms (hook, pull, push, fat, thin,
lack_of_distance, inconsistent_contact, shank) have their KB files
loaded and their causes matched by the same matcher code — that
part is validated by `test_matcher.py` from Phase 3 — but the LLM
handling of each is inferred, not tested.

Special-case branches specifically deferred:
- **`shank` symptom**: system prompt instructs the LLM to add a
  sentence acknowledging that shanks often appear and disappear
  suddenly with a tension/confidence component. Not exercised.
- **`inconsistent_contact` symptom**: system prompt instructs the
  LLM to reframe output as "here are where your swing varies most,
  ranked by magnitude" (variance sources) rather than mechanical
  causes. Not exercised. Also uses `stddev_gt` mode indicators
  exclusively, which we didn't hit in any Phase 4 test.

Phase 5 real-user data or additional per-symptom sanity scripts
will exercise these.

### `annotated_output_dir` not exercised

`analyze_swings()` accepts an optional `annotated_output_dir` that
triggers `render_segmented_pose_video()` to emit the annotated MP4
alongside pose analysis. Phase 4 tests all pass `None`. Rendering
was validated in Phase 1's `test_segmented_visualizer.py`; the
composition of pipeline + rendering is inferred from the module
integration but not empirically verified in one shot.

### Handedness always right-handed

`analyze_swings()` accepts a `handedness` parameter defaulting to
`Handedness.RIGHT_HANDED`. All Phase 2/3/4 test data is right-
handed. Left-handed pose extraction, segmentation, and feature
computation are all handedness-aware through the `lead()` and
`trail()` resolvers, but no left-handed swing has been analyzed
end-to-end. Phase 5's UI should include a handedness toggle.

---

## Costs and budget

- Sonnet 4.6 pricing: $3 / $15 per M tokens (input / output)
- Cache write: 1.25x input rate
- Cache read: 0.10x input rate

Phase 4 total spend across all live tests (approximate):
- `test_diagnosis.py` first run: $0.035
- `test_diagnosis.py` re-run after z-score fix: $0.030
- `test_pipeline.py` first version: $0.020
- `test_pipeline.py` updated with two cases: $0.030
- Miscellaneous debugging: ~$0.010

Total: **~$0.13** spent on live API testing in Phase 4.

Phase 5 real-user development budget expectation: $2-5 for iteration
including running the pipeline against every uploaded video during
end-user testing.

---

## Deferred to Phase 5+ (real-user data)

- All 9 symptoms exercised with real users
- Retry path exercised (if LLM ever produces invalid output)
- Handedness toggle in UI
- Fallback-rate calibration for pull/push symptoms (which lost 2
  causes each to the invisible-axis principle and are structurally
  more likely to fall back)
- Feel selection quality assessment across a diversity of user
  contexts
- Annotated video rendering exercised at scale

---

## Deferred to v2

See `docs/v2_priorities.md` for the full list. The single highest-
impact v2 change is **face-on camera view** — restores five dropped
KB causes (weak grip, strong grip, aim left, aim right, no ground
use) and returns three swapped-to-fallback causes (reverse pivot,
hanging back, early extension) to their proper primary indicators.
This became more visible during Phase 4 testing: the Case B
fallback message explicitly told the user that grip and alignment
are "invisible from this angle" — the tool is honest about its
limitations, but the limitations are more consequential than the
Phase 2 drops made them look.