# Phase 5.1: General swing analysis (symptom-optional mode)

Design notes for the general-analysis path added mid-Phase-5,
between the backend API completion and the frontend build.
Complements `phase4_notes.md`. Written before implementation so
the intent is captured; empirical findings appended as validation
runs.

## Motivation

The v1 spec is symptom-driven by design. But real user framing
often doesn't fit that shape:

> "Sometimes I can't really explain what's wrong with my swing.
> It could be one thing, could be multiple things."

Forcing symptom selection when the user has no specific complaint
either produces low-quality diagnoses (they guessed and picked a
symptom that doesn't match what's happening) or drives them away
before analysis runs at all.

## What "general analysis" means

The user hasn't reported a ball-flight symptom. They want the tool
to name the most notable characteristics of their swing.
Mechanically: rank every unique cause across all loaded symptom KBs
against the user's swings, surface the top 1-3, narrate with the
same feel-forward voice as symptom mode.

## Distinguishing general analysis from adjacent things

**vs. `inconsistent_contact` symptom.** The Phase 3
inconsistent-contact KB scores against feature *variance* across
swings (stddev_gt indicators). It answers "where does your swing
vary most from swing to swing?" — a completely different question.
A player with a repeating slice would score LOW on
inconsistent-contact indicators (their swing is consistent, just
consistently wrong) and receive the fallback message. General
analysis scores against feature *values*, same as every other
symptom-mode diagnosis.

**vs. multi-symptom selection.** Architecturally identical to
general analysis. If we let the user pick slice + fat_contact
together, we'd have to pool the causes from both KBs, dedupe them
(because early_extension appears in both), and produce a
non-symptom-anchored LLM output. That's exactly what general
analysis does. Multi-symptom is a UI variation on the same
underlying feature; we build the feature once.

**vs. ranking features by z-score.** Would be simpler to implement
but semantically wrong. The KB's value is that each cause carries
its fix, feel, and drills. Ranking features drops all of that and
reduces the tool to a readings report ("your trail wrist is 3.2
stddevs cupped" — so what?). Ranking causes preserves the
diagnostic + coaching output.

## Locked-in design decisions

Not to be relitigated without new evidence.

### 1. Rank causes, not features

General mode's ranked list is `list[RankedCause]`, identical type
to `match_symptom`'s output. Same scoring, same fallback floor,
same consumers downstream.

### 2. Dedup by `cause_id`: enforce diagnostic, pool coaching

The Phase 3 causes-catalog consistency rule was explicit that
shared causes across symptom files use identical
**indicators** (feature / threshold / weight). Empirical audit
during Phase 5.1 revealed the rule is silent on coaching content
(**feels**, **drills**): those legitimately vary per symptom
because the same underlying fault produces different ball flights
in different contexts, and the coaching cue that helps a player
fix "early extension producing a shank" reads differently from
the cue that helps them fix "early extension producing fat
contact." Both feels are valid — they're the same physical
correction described in the register the player will recognize
given their reported symptom.

General mode splits the two categories:

- **Diagnostic fields (indicators, fix, category)** are enforced
  identical across every symptom file that hosts the cause. If
  divergence is found, `match_general` raises `ValueError`. See
  `_assert_diagnostic_identity`.
- **Coaching fields (feels, drills)** are pooled: the canonical
  general-mode `Cause` carries the *union* of feels across all
  its host files (dedup by feel text) and the union of drills
  (dedup by name), with first-occurrence order preserved. See
  `_pool_feels` / `_pool_drills` and the pooling call in
  `_collect_unique_causes`.

**Indicator equality is matcher-relevant fields only.** The
`Indicator` Pydantic model has six fields: `feature`, `mode`,
`operator`, `threshold`, `confidence_weight`, and `reasoning`.
The consistency check compares only the first five. `reasoning`
is per-file documentation — a short prose note about why this
indicator is in this cause for this symptom — and it may (and
often does) vary across symptom files without any diagnostic
significance. Neither the matcher nor the LLM reads it (Phase 4
notes call it out as explicitly withheld from LLM view).

Pydantic's default `__eq__` compares all fields including
`reasoning`, so the assertion uses a dedicated
`_indicators_matcher_equal` helper rather than list equality
directly. This was learned empirically during Phase 5.1
implementation: the initial byte-identical assertion fired on all
4 shared cause_ids in the KB because reasoning notes had drifted
across files; investigation confirmed all diagnostic fields were
in fact identical.

**What the LLM sees in general mode.** For a shared cause,
`Cause.feels` in general mode contains the union of feels from
every symptom file that hosts the cause. Example:
`early_extension` appears in 6 symptom files with different feels
tailored per symptom; the general-mode `Cause` may carry ~6-10
unique feels. The LLM's feel selection is unchanged in mechanism
(pick a `feel_id`); it just has a richer vocabulary to choose
from, and can select based on `user_context` (e.g., "I've been
shanking" → pick the shank-context feel from the pool).

Fields still allowed to differ silently: `description` (prose
tailored per symptom), `confidence` (Phase 2 metadata not read
by matcher), and `Indicator.reasoning` (per-file authoring notes).

### 3. Same 0.5 fallback floor

FALLBACK_SCORE_FLOOR is unchanged in general mode. Reasoning:
- The floor was chosen so a single 0.4-weight corroborator can't
  produce a diagnosis alone. That reasoning is mode-independent.
- Consistency across modes: "not enough signal" means the same
  thing whether the user reported a symptom or not.

### 4. Same 1 + 2 output structure

Primary + up to 2 secondary in diagnosis mode; up to 5 near-misses
in fallback mode. Same limits as symptom mode.

General mode has more candidates in the ranking pool (~17-20
unique causes vs. 3-5 per symptom), so a naive "show more" is
tempting. Rejected because:
- Cognitive load: 3 things to work on is already a lot for a
  golfer at the range. 5+ becomes noise.
- LLM output quality: the model picks the most actionable causes;
  giving it 15 candidates dilutes selection quality vs. giving it
  the 3-5 that cleared the floor.

Debug trail (`ranked_causes` in the AnalysisResult) still contains
every scored cause for observability.

### 5. `DiagnosticOutput` Pydantic schema unchanged

The existing schema (`summary`, `primary`, `secondary`,
`fallback_message`) is mode-neutral. `cause_id` values are globally
unique in the KB, so they resolve unambiguously regardless of
symptom scope. `feel_id` and `drill_ids` still index into the cited
cause. No new fields, no new models.

`validate_against_kb` needs one small change: the
`ranked_cause_ids` list it validates against now comes from
`match_general`'s output rather than `match_symptom`'s. The
validator's logic (cited cause must be in the ranked list) is
already mode-neutral.

### 6. Extend existing modules; do not fork

New modules with parallel implementations of ranking + prompting
would drift over time. The general path shares ~90% of the logic
with symptom mode. Cleaner to add `match_general` alongside
`match_symptom` in the same file, and add a `general_diagnosis` /
`general_fallback` branch to `build_prompt`.

### 7. Empty/None symptom in the API triggers general mode

`analyze_swings` gains `symptom: str | None`. When `None`, pipeline
routes through `match_general` + general-mode prompt. The API
layer's `symptom: str = Form("")` becomes `str | None`; empty
string or absent → general.

## Deduplication algorithm

```python
seen: dict[str, Cause] = {}
for symptom in kb.loaded_symptoms():
    for cause in kb.get_causes(symptom):
        if cause.cause_id in seen:
            existing = seen[cause.cause_id]
            _assert_causes_identical(existing, cause)  # raises ValueError
        else:
            seen[cause.cause_id] = cause
unique_causes = list(seen.values())
```

`_assert_causes_identical` checks:
- Indicator lists match under equality (Pydantic models are
  comparable by value)
- Feels lists match
- Drills lists match
- Fix.technical_instruction matches

Confidence label and description are NOT required to match.
Confidence label is Phase 2 metadata, not diagnostic; description
is prose that may be tailored per symptom.

## Prompt reframe

The system prompt has a mode-dispatched opening paragraph:

**Symptom mode (current):**
> The user reported symptom ``{symptom}``. Your job is to explain
> why the user is producing this ball flight based on the ranked
> causes below.

**General mode (new):**
> The user has not reported a specific ball-flight symptom and
> wants a general analysis of their swing. Your job is to identify
> the most notable characteristics of their swing based on the
> ranked causes below, framed as observations rather than as
> explanations for a specific miss.

Voice differences in the technical_explanation:
- Symptom: *"Your ball is starting left and curving right because
  your face is open at impact — your trail wrist is 52° cupped at
  the top…"*
- General: *"The most notable pattern in your swing is a cupped
  position at the top of the backswing — your trail wrist is 52°
  extended…"*

Feel selection, drill selection, and coaching-unit-citation rules
are unchanged.

Symptom-specific branches in the current system prompt
(`inconsistent_contact` reframe, `shank` psychological caveat)
are skipped in general mode. There's no symptom to trigger them.

## Fallback semantics

Same 0.5 floor. Different message text.

**Symptom-mode fallback (current):**
> You reported ``{symptom}`` but nothing in the ranked causes
> clearly diagnoses it. Cite the closest candidate; mention
> invisible-axis blind spots (grip, alignment, weight, face-on);
> suggest more swings or a clearer example.

**General-mode fallback (new):**
> Nothing in the user's swing stood out clearly from typical.
> Cite the closest observations from the ranked list. Mention that
> a nothing-stood-out result can mean either (a) their swing is
> close to neutral for the features v1 can measure, or (b) the
> specific issue lies in an area invisible from down-the-line
> (grip, alignment, weight distribution). Suggest reporting a
> specific symptom if they have one, or uploading swings shot from
> a face-on angle when v2 supports it.

## What this is not

- Not a general "swing score" like Swing Sensei. No overall grade.
- Not a feature-readings dashboard. Output is diagnostic causes
  with feels and fixes, same as symptom mode.
- Not a workaround for missing symptoms. If a specific symptom
  fits, symptom mode gives a better diagnosis because it can use
  symptom-specific framing and select from causes tuned for that
  ball flight.
- Not multi-symptom selection UI. Multi-symptom is architecturally
  identical to general analysis; UI dresses it up differently but
  the underlying feature is one and the same.

## Empirical findings

Populated as validation runs.

*(Test A — general mode on swing_16 alone)*: to be filled.

*(Test B — general mode on swing_16 + swing_09 pair, fallback expected)*: to be filled.

*(Test C — API path with no symptom)*: to be filled.

## Deferred / v2 candidates

- **Multi-symptom UI mode.** If real users want it, wrap general
  mode with a UI that lets them list 2-3 candidate symptoms; use
  those to bias the LLM's opening framing but keep the underlying
  matcher call as general.
- **Symptom prediction.** If the general-mode ranked list produces
  a clear cause associated primarily with one symptom, hint at
  the symptom in output ("this pattern most commonly produces a
  slice — is that what you're seeing?").
- **General-mode fallback improvements.** After real user data,
  refine the fallback text; may want to categorize "close to
  neutral" vs. "measurement blind spot" more precisely.