# Phase 3 Notes

Running notes on Phase 3 work: KB authoring and matcher. This
document complements `phase1_notes.md` and `phase2_notes.md` and
records findings, design decisions, and limitations as they emerged.

## Phase 3 goal

Given (aggregated features across 3-5 swings, user-reported symptom)
→ ranked list of causes with matched-indicator details, ready to
hand to the LLM layer in Phase 4.

Built:
- `kb/baseline.yaml` — 36-feature statistical baseline from 15
  normal swings
- `src/golf_diagnostic/kb/loader.py` — Pydantic-validated KB loader
- `src/golf_diagnostic/diagnosis/matcher.py` — matcher with
  consistency filter and fallback
- `scripts/regenerate_baseline.py` — regenerates baseline.yaml from
  swings labeled `type: normal`
- `scripts/audit_kb_against_normals.py` — audits KB thresholds by
  running the matcher against each normal swing individually
- `scripts/test_matcher.py` — end-to-end sanity tests including
  fault-demo validation
- 9 symptom KB files (`kb/<symptom>.yaml`), 33 causes total

Phase 3 exit criterion met.

---

## Locked-in design decisions

Six design decisions established in Phase 3 that constrain Phase 4+
work. These are not to be relitigated without new evidence.

### 1. Three-mode indicator design

Each KB indicator declares `mode: raw | zscore | stddev_gt`:

- **raw** — feature has real-world coaching meaning (wrist angles
  in degrees, spine angles, tempo). Threshold is the raw value.
- **zscore** — feature is a unitless proxy (rotation proxies,
  target-axis displacements). Threshold in stddevs from baseline
  mean.
- **stddev_gt** — variance indicator for inconsistent contact.
  Threshold is a raw stddev value; the indicator matches the user's
  cross-swing stddev of a feature.

Why not raw-only: a raw threshold on `shoulder_rotation_proxy_at_P4`
would be a number like −0.55 that's unreadable without knowing the
baseline (mean −0.70, stddev 0.03). Every KB reviewer would need to
context-shift to interpret it. z-score mode puts the statistical
context in one file (`kb/baseline.yaml`) and lets KB entries express
"how many stddevs from population baseline" directly.

Why not z-score-only: locks KB thresholds to Jonathan's 15-swing
baseline forever. If the baseline is regenerated (v2 refilming,
schema changes) all z-thresholds implicitly retune. Sometimes
desirable, sometimes not. Raw mode keeps coaching-derived thresholds
(15° cupped wrist) stable regardless of baseline changes.

The three modes coexist cleanly in the loader (Pydantic Literal) and
evaluator (small operator dispatch table). No expression language,
no eval, no string parsing.

### 2. 60% consistency filter across swings

An indicator matches at the cause level only if it fires on ≥60% of
the user's uploaded swings. `stddev_gt` indicators bypass this filter
(variance is inherently cross-swing).

Purpose: suppress single-swing anomalies. Real users upload 3-5
swings; a diagnosis should require the fault to appear consistently.
The audit script runs each swing individually (n=1) which is a
harsher test than production — a lot of audit false positives get
suppressed by the consistency filter in real 3-5-swing uploads.

Not tuned per-cause. Not tuned per-indicator. Uniform module-level
constant. Revisit if Phase 5 real-user data shows a symptom systematically
needs a different threshold.

### 3. Score-based ranking with 0.5 fallback floor

A cause's score is the sum of matched indicators' `confidence_weight`
values. Ranked descending by score. Ties broken by KB author order
(stable sort). No normalization (max scores differ per cause and
that's fine — ranking within a symptom is what matters).

Fallback triggers when:
- No cause has any matched indicators, OR
- Top cause has score < 0.5

The 0.5 floor was chosen as "a single 0.4-weight corroborating hit
shouldn't produce a diagnosis." When a primary indicator has weight
0.5, a single fire just clears floor — that's the design point.
When weight is 0.4, cause needs another indicator to clear.

### 4. Causes-catalog consistency rule

Shared causes across symptom files (early_extension, hanging_back,
casting_early_release, over_the_top-style, reverse_pivot) use the
SAME feature, threshold, and weight across every file. Rationale:
same physical cause → same indicators regardless of what symptom it
produces. Discrimination between symptoms happens at symptom-report
time, not at KB-indicator time.

Concrete example: `early_extension` appears in 6 symptom files
(slice, pull, push, fat_contact, thin_contact, shank). All 6 use:
- `spine_angle_change_P1_to_P7 zscore lt -1.5` weight 0.7
- `hip_vertical_change_P1_to_P7 zscore gt 1.5` weight 0.3

The audit consistently fires early_extension on swing_11 in every
symptom file — same feature reading, same threshold, same result.
That's the rule working correctly, not a bug.

### 5. Weight tiers

Explicit per-indicator weights, not derived from cause confidence
label. Empirical tiers that emerged:

- **1.0**: primary indicator of a validated cause with strong demo
  separation (trail_wrist_angle_at_P4 on cupped, hip_rotation at P4
  on short backswing).
- **0.7**: primary indicator of a plausible cause with clean baseline
  behavior (spine_angle_change_P1_to_P7).
- **0.5**: primary indicator of a plausible cause where the feature
  has known limits (P7 wrist noise, high-CV proxy features). Single
  fire just clears floor.
- **0.4**: below-floor weight for stopgap indicators (over_the_top
  shoulder-only, arms_dominant_downswing) or weak-confidence causes
  (reverse_pivot). Cannot diagnose alone; needs corroboration.
- **0.3**: corroborator or feature explicitly flagged as noisy /
  confounded in phase2_notes.

The `confidence` label on each cause (validated/plausible/weak) is
documentation only. Ranking uses weight sums, not confidence labels.

### 6. stddev_gt thresholds at ~2× population baseline stddev

For inconsistent_contact variance indicators. The naive "75% of
population stddev" rule failed empirically — Test E in
`scripts/test_matcher.py` fired every indicator on the 15-normal
group because population stddev IS the reference distribution, not
an upper bound. 2× threshold catches sessions where within-session
variance exceeds full cross-session population variance, which is
meaningfully abnormal.

Placeholder tuning — Phase 5 real-user data will retune. Documented
in `kb/inconsistent_contact.yaml` file-level comment.

---

## What the audit script is (and isn't)

The audit runs each normal swing individually against each symptom's
KB. It answers: "if this single swing were uploaded by a user
reporting this symptom, would the tool diagnose them?"

It does NOT establish diagnostic accuracy. It's a threshold-tuning
tool. Its purpose is to catch obvious errors — a threshold so loose
that half of normal swings fire it, a mode misapplied so a feature
never fires, a cause with no working indicators.

Every audit false positive is one of three things:
1. Threshold too generous → tune it
2. Real anomaly in a normal-labeled swing (which is expected because
   "normal" means "not intentionally faulty," not "faultless")
3. MediaPipe misread a frame (landmark noise)

The audit surfaces the pattern; interpretation is separate. Not
every audit hit needs a threshold fix.

Persistent false positives that surfaced across multiple audits:
- **swing_11** fires early_extension in slice, pull, push, fat, thin,
  shank. Real signal: spine_angle_change_P1_to_P7 = −12.3° on a
  swing with clean pose landmarks (visually verified). Real
  spine-straightening, not measurement noise. Accepted.
- **swing_06** fires shoulder_rotation_proxy_at_P7 above threshold
  (z ≈ +2.3) in slice, pull, push, shank. User confirmed swing_06
  produced a hard slice in real ball flight — the indicator is
  measuring a real slice-conducive shoulder pattern. Accepted.
  Kept over_the_top weight at 0.5 based on this evidence rather
  than dropping it defensively.
- **swing_10** fires hand_distance_from_body_at_P1 (z ≈ −2.48) in
  shank. Real setup pattern (hands hanging close to body); "normal"
  label just means "not intentionally too close." Accepted.

---

## Cleanly validated pipeline tests

Three end-to-end validated matches against real fault demos in
`scripts/test_matcher.py`:

- **Test B: swing_16 (cupped_lead_wrist_at_top) vs slice**
  cupped_lead_wrist_at_top score 1.40 (primary + lead-side corroborator)
- **Test C: swing_25 (short_backswing) vs lack_of_distance**
  insufficient_body_rotation score 1.50 (hip primary at z=+4.35,
  shoulder corroborator at z=+3.32). Confirms incidental drift
  correctly stays under fallback floor — arms_dominant_downswing
  and casting_early_release fire at 0.40 each below the 0.50 diagnostic
  threshold.
- **Test D: swing_22 (hanging_back) vs push**
  hanging_back score 0.50 (just clears floor). Documents that
  "validated with modest signal" is a real category — the demo
  fires the cause but doesn't dominate.

Test E (15 normals grouped vs inconsistent_contact) confirms
fallback triggers on a homogeneous population — after the 2×-baseline
threshold fix. Test F (5 disparate fault demos vs inconsistent_contact)
fires only inconsistent_top_of_backswing at 0.5, which is a real
diagnostic finding: **a bag of specific faults doesn't necessarily
present as "inconsistent contact"** because within-session variance
across faults doesn't dominate feature stddev uniformly. A user with
5 specific-fault swings would be caught by the specific-symptom KB
based on their symptom report, not by inconsistent_contact.

---

## Symptom-by-symptom summary

| Symptom | Causes | Validated demos | Notes |
|---|---|---|---|
| slice | 4 | swing_16 (cupped) | over_the_top weight kept at 0.5 based on swing_06 ball-flight evidence |
| hook | 4 | swing_17 underperformed (documented in phase2) | bowed demo signal too weak due to Jonathan's natural cupping |
| pull | 2 | none | Two v1 drops (aim-left, ball-position); one merged (closed shoulders) — most-degraded symptom |
| push | 3 | swing_22 (hanging_back, modest signal) | |
| fat_contact | 4 | (indirectly via push swing_22) | Pure re-composition of prior-symptom causes |
| thin_contact | 4 | none | New: loss_of_posture (uses spine_angle_change_P1_to_P4) |
| lack_of_distance | 5 | swing_25 (short_backswing) | Includes tempo (direct measurement, but no clean tempo demo) |
| inconsistent_contact | 5 | none — needs multi-swing groups | Only symptom using stddev_gt mode |
| shank | 4 | none | Cause 4 (diving into ball) merged into cause 1 (early extension) as redundant |

Total: 9 symptoms, 33 causes.

---

## Feature usage summary

Features referenced by KB indicators, sorted by count of symptoms
touching them:

Across-symptoms features:
- `spine_angle_change_P1_to_P7` — 6 symptoms (all early_extension)
- `hip_vertical_change_P1_to_P7` — 6 symptoms (all early_extension corroborator)
- `head_displacement_P1_to_P7_target_axis` — 2 symptoms (hanging_back in push, fat)
- `lead_wrist_angle_at_P5_proxy`, `trail_wrist_angle_at_P5_proxy` — 3 symptoms (casting)
- `shoulder_rotation_proxy_at_P7` — 4 symptoms (over_the_top variants)
- `hip_rotation_proxy_at_P7` — 3 symptoms (stuck-path variants + arms_dominant)
- `head_displacement_P1_to_P4` — 2 symptoms (reverse_pivot)

Features used by exactly one symptom cause:
- `trail_wrist_angle_at_P4`, `lead_wrist_angle_at_P4` — slice cupped, hook bowed
- `trail_wrist_angle_at_P7`, `lead_wrist_angle_at_P7` — hook trail_hand_overactive, thin scoop
- `spine_angle_change_P1_to_P4` — thin loss_of_posture (only)
- `hip_rotation_change_P7_to_P10` — hook body_stall (only)
- `lead_elbow_angle_at_P4` — lack_of_distance collapsed_swing_radius
- `lead_arm_angle_at_P7` — hook body_stall corroborator, lack_of_distance collapsed_swing_radius
- `hand_distance_from_body_at_P1` — shank standing_too_close, inconsistent_setup (stddev_gt)
- `hand_distance_from_body_at_P7` — shank arms_disconnect
- `lead_arm_to_torso_angle_at_P5_proxy` — shank arms_disconnect
- `hand_path_proxy_at_P5_proxy` — shank out_to_in_arms_pushed_away
- `tempo_ratio`, `total_swing_duration` — lack_of_distance wrong_tempo, inconsistent_tempo (stddev_gt)
- `head_vertical_change_P1_to_P7` — thin scoop corroborator, variable_low_point (stddev_gt)

Features never referenced by any KB indicator (per-swing mode):
- `lead_wrist_angle_at_P1`, `trail_wrist_angle_at_P1` — used in
  variance form only (as stddev_gt in inconsistent_wrist_at_impact,
  but wait — actually these aren't. Only P4 and P7 wrist stddevs
  used. P1 wrist features are currently unreferenced. Retained in
  schema for completeness.)
- `spine_angle_at_P1`, `spine_angle_at_P4`, `spine_angle_at_P7` —
  referenced only via the delta features. Kept as they're the
  operands of the deltas.
- `knee_flex_lead_at_P1`, `knee_flex_trail_at_P1` — variance form
  only (inconsistent_setup uses lead; trail unused).
- `stance_width_at_P1` — retained for v2, no v1 KB use.
- `ankle_displacement_at_P7` — retained for v2, no v1 KB use
  (flagged unreliable in phase2_notes).
- `hip_displacement_P1_to_P7_target_axis` — retained for v2 (bump-and-hang faults).

---

## Empirical patterns worth carrying forward

### Tight-CV features need 3σ thresholds

Rotation proxies at P4 have ~5% CV. Threshold at 2σ (initial attempt
for `insufficient_body_rotation`) surfaced swing_01 (a baseline member
at z=2.24) as false positive. Threshold at 3σ preserved separation
while still firing the validated demo (swing_25 at z=+4.44).

Pattern: for features with population CV < 10%, use ≥3σ thresholds.
Baseline distribution's own tail sits beyond 2σ when spread is tight.

### High-CV features can't diagnose alone

`shoulder_rotation_proxy_at_P7` has 59% baseline CV. A z=+1.5 threshold
fires on real over-the-top swings (swing_20 z=+2.3, swing_06 z=+2.3
with confirmed slice) but sits close enough to baseline that many
normals also reach it. Weight is capped at 0.4-0.5 for these features
so they can contribute to ranking but not diagnose alone. The
`trail_elbow_position_at_P4_to_P7` feature (not built in v1) is the
intended primary — shoulder rotation at P7 is a stopgap.

### Categories of feature limitation

A feature can be limited in three distinct ways that all look
similar in audits but need different responses:

1. **Feature-intrinsic weakness** (P7 wrist motion jitter, 
   hip_vertical_change rotation confounding). Feature measures
   what it claims but the signal is diluted. Response: low weight,
   corroborating-only.
2. **Demo-execution gap** (bowed demo, slow-tempo demo). Feature
   works fine, demo just didn't produce the intended fault. Response:
   set threshold from feature geometry, accept that this specific
   demo won't validate.
3. **Threshold-baseline collision** (tight-CV features, wide-baseline
   features). Feature works fine, but baseline distribution's tail
   sits at the threshold. Response: raise threshold or drop weight;
   distinguish "genuinely extreme" from "baseline tail."

The audit surfaces all three the same way. Interpretation matters.

---

## Deferred to Phase 4+

- **trail_elbow_position_at_P4_to_P7 derived feature.** Would give
  a real primary indicator for over-the-top (slice), stuck-inside
  (hook), out-to-in path variants (pull, push, shank). Currently
  four causes depend on this feature via shoulder-rotation stopgaps
  at weight 0.4-0.5. Building it would let those causes actually
  diagnose alone. Belongs in a small derived-features extractor or
  in the orchestrator.
- **Casting fault demo.** Three symptoms (fat, thin, lack_of_distance)
  use casting_early_release with no validating demo. A deliberately-cast
  swing_XX would confirm the P5-proxy features move in the expected
  direction.
- **Body-stall fault demo.** Would validate hook cause 4 primary
  (hip_rotation_change_P7_to_P10).
- **Ball-position detection.** Would restore push cause 4, pull cause
  3, thin cause 5 (currently deferred entries in labels.yaml with
  swing_29 and swing_30).

## Deferred to Phase 5+ (real-user data)

- Inconsistent_contact stddev thresholds (2× baseline placeholder).
- All confidence weights and thresholds across the KB — every
  numeric decision was made from Jonathan's 15-swing baseline plus
  fault demos, and real user data will inevitably shift what
  values are appropriate.

## Deferred to v2

- Face-on camera view — restores weight distribution, alignment,
  grip strength, lead-side wrist visibility (5 dropped causes).
- 120+ fps filming — restores reliable P7 wrist measurement
  (2 dropped causes: hook cause 5, thin cause 4).
- Real P5 detection instead of interpolation — strengthens all
  casting causes.