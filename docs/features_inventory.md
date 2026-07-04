> **Phase 2 update: trail-side wrist features are now primary.**
>
> The "high-leverage features" section at the bottom of this document
> originally lists `lead_wrist_angle_at_P7` and `lead_wrist_angle_at_P4`
> as the most diagnostically important features in the KB. For v1
> (down-the-line video), those features are demoted to secondary
> status because lead-side landmarks are frequently occluded
> (visibility 0.1-0.6 vs. 0.85-0.97 for trail-side). The
> `trail_wrist_angle_*` features take their place as the primary
> measurement.
>
> Both lead and trail versions are still defined and computed; the
> change is about which is treated as primary in KB matching, not
> what gets stored. See `docs/measurement_visibility_decisions.md`.

> **Phase 2 update: rotation proxies are unitless normalized ratios.**
>
> The rotation-proxy feature descriptions below (shoulder_rotation_proxy_*
> and hip_rotation_proxy_*) originally suggested these are measured in
> degrees relative to an address line. The v1 implementation instead
> produces unitless ratios: signed image-x separation of paired
> landmarks (trail − lead), normalized by ankle-to-hip vertical distance
> at P1. Empirical values: shoulder_at_P4 mean −0.70, hip_at_P4 mean
> −0.40, hip_at_P10 mean +0.44 across normal swings. Negative =
> rotated in backswing direction; positive = rotated in follow-through
> direction. See `docs/phase2_notes.md`.

> **Phase 2 update: hip_vertical_change_P1_to_P7 is corroborating, not primary.**
>
> The entry below originally described this as the primary
> early-extension indicator ("ties with lead_wrist_angle_at_P7 for
> most-referenced feature"). Empirical validation showed the
> measurement is CONFOUNDED by natural hip rotation — normal swings
> already show 0.05-0.15 units of "hip rising" between P1 and P7 as
> a byproduct of hips rotating open. The feature works but doesn't
> discriminate faulty from normal on its own.
>
> Primary early-extension indicator in v1 is now
> `spine_angle_change_P1_to_P7` (from posture extractor, delta-based
> so unconfounded by rotation). `hip_vertical_change_P1_to_P7` is
> retained as a corroborating indicator only.

> **Features removed from v1 due to the "invisible axis" principle.**
>
> Six features cannot be measured reliably from down-the-line 2D pose
> because the signal they carry lives along or rotates around the
> camera's line of sight:
>
> - `weight_distribution_proxy_at_{P1, P4, P7}` — target-axis
>   lateral measurement; target line IS the camera axis. Attempted
>   implementation produced ~1.0 constants across all 30 swings.
> - `shoulder_line_at_P1`, `hip_line_at_P1` — alignment defined
>   relative to the target line; foot-line reference is itself along
>   the camera axis. Attempted implementation produced ±90° values
>   with sd 60°+ (unstable around a singularity).
> - `lead_hand_knuckle_visibility_at_P1` — grip strength rotates
>   around the shaft axis, which is the camera axis at address.
>   MediaPipe pose lacks true hand keypoints. Not attempted.
>
> See `docs/measurement_visibility_decisions.md` for the full
> principle and `docs/phase2_notes.md` for empirical details.
>
> Consequence: five KB causes dropped from v1 — slice cause 3 (weak
> grip), hook cause 3 (strong grip), pull cause 2 (aim left), push
> cause 3 (aim right), lack-of-distance cause 5 (no ground use).
> Three causes had their primary indicator swapped for a fallback:
> reverse pivot → `head_displacement_P1_to_P4` (weak), hanging back
> → `head_displacement_P1_to_P7_target_axis` (validated), early
> extension → `spine_angle_change_P1_to_P7` (plausible).

---

## Conventions

Before listing features, three conventions to lock in now so the
schema is consistent:

1. **Signed values for direction.** Where a feature can vary in two
   directions (cupped vs bowed wrist), use a single signed feature
   rather than two separate features. Convention: positive = one
   direction, negative = the other, zero = neutral. Document the sign
   convention per feature.

2. **_proxy suffix for inferred features.** Any feature that isn't
   measured directly from pose keypoints but inferred from them
   (hip rotation from hip-keypoint positions, shoulder rotation from
   shoulder-keypoint positions) gets the `_proxy` suffix. Makes it
   visible in the KB which indicators are direct measurements vs
   estimates.

3. **_at_P5_proxy for between-checkpoint features.** Features that
   want a value at P5 in v1 get computed by interpolating between
   P4 and P7 wrist/arm angles. The suffix doubles up —
   `_at_P5_proxy` — to flag both that the checkpoint is interpolated
   and that the underlying feature is a proxy. If real P5 detection
   is added in a v1 patch, these become `_at_P5` and the interpolation
   logic is replaced.

---

## P1 features (address)

### Joint angles and positions

- **`lead_wrist_angle_at_P1`** — flex/extension of lead wrist at
  address. Signed: positive = cupped, negative = bowed. Used:
  variance only (inconsistent-contact uses _stddev form).

- **`trail_wrist_angle_at_P1`** — same for trail wrist. Used:
  variance only.

- **`spine_angle_at_P1`** — forward tilt of spine from vertical,
  measured in 2D from shoulder-to-hip line vs vertical. Used:
  baseline for spine-angle comparisons at P4 and P7; variance form
  for inconsistent setup.

- **`knee_flex_lead_at_P1`** — interior angle at the lead knee
  (hip → knee → ankle). 180 = straight, smaller = more flexed.
  Variance form used by inconsistent-setup.

- **`knee_flex_trail_at_P1`** — same for trail knee.

### Body positions and setup

- **`hand_distance_from_body_at_P1`** — perpendicular distance from
  hand midpoint to torso axis (shoulder-hip line) at address,
  normalized by ankle-to-hip vertical. Used by shank cause 2
  (standing too close). ~19% CV on normal baseline; requires
  conservative KB thresholds.

- **`stance_width_at_P1`** — normalized distance between ankles.
  Retained for reference; no v1 cause currently uses it as a
  primary indicator. May be picked up in v2.

### Ball-position-dependent features (deferred to v2)

Ball position features require reliable ball detection in-frame,
which v1 does not implement. These are deferred to v2 or to
user-provided free-text context.

- `lead_foot_position_at_P1` relative to estimated ball position —
  would drive pull cause 3, push cause 4, thin cause 5. Not in v1
  schema.

---

## P4 features (top of backswing)

### Wrist angles

- **`lead_wrist_angle_at_P4`** — signed (+ cupped, − bowed). Used by
  slice cause 1 and hook cause 1. In v1, trail-side is the primary
  measurement; lead-side is a corroborating indicator only.
  Variance form used by inconsistent-contact cause 5.

- **`trail_wrist_angle_at_P4`** — same for trail wrist. **Primary
  wrist measurement in v1.** ~52° separation between cupped and
  bowed fault demos, high visibility.

### Rotation proxies

- **`shoulder_rotation_proxy_at_P4`** — unitless ratio (see the
  Phase 2 update at the top). Used by lack-of-distance cause 1
  (under-rotated) and pull cause 4 (closed/under-rotated at top).
  Variance form used by inconsistent-contact cause 5.

- **`hip_rotation_proxy_at_P4`** — same for hips. Used by
  lack-of-distance cause 1.

### Body position and posture

- **`spine_angle_at_P4`** — spine tilt at top. Used as the P4
  operand of `spine_angle_change_P1_to_P4` (loss of posture).

### Arm structure

- **`lead_elbow_angle_at_P4`** — bend in lead arm at top. Used by
  lack-of-distance cause 6 (collapsed swing radius).

---

## P5 features (interpolated, v1 only)

Wrist measurement side at P5 differs from P4/P7. At mid-downswing,
lead-side wrist tracking is empirically less noisy than trail-side
(normal baseline stddev 12.7° vs 20.0°). Motion speed at frame midpoint
dominates over visibility as the noise source. KB matching should use
lead_wrist_angle_at_P5_proxy as primary for casting causes,
with trail_wrist_angle_at_P5_proxy as corroborating only — the opposite
of the P4/P7 rule.

All features here are interpolated between P4 and P7. Flagged for
upgrade to direct P5 detection if Phase 3 testing shows casting
diagnoses are noisy.

- **`lead_wrist_angle_at_P5_proxy`** — wrist angle in early
  downswing. Used by fat cause 3, thin cause 3, lack-of-distance
  cause 3 (all casting-related).

- **`trail_wrist_angle_at_P5_proxy`** — same for trail wrist.

- **`lead_arm_to_torso_angle_at_P5_proxy`** — angle between lead arm
  and torso in early downswing (connection indicator). Used by
  shank cause 5.

- **`hand_path_proxy_at_P5_proxy`** — direction of hand movement
  P4 → interpolated P5. Operationalized as the change in
  hand-to-body distance. Positive = hands moved outward (away from
  body). Used by shank cause 3.

---

## P7 features (impact)

This checkpoint has the highest feature density — most diagnostic
signal lives here.

### Wrist angles

- **`lead_wrist_angle_at_P7`** — signed (+ cupped, − bowed).
  Motion-jitter noisy at 60fps. Used by slice cause 1, hook cause 1,
  thin cause 4 (scoop), hook cause 5 (paired with trail for flip).
  Variance form used by inconsistent-contact cause 4.

- **`trail_wrist_angle_at_P7`** — signed. Motion-jitter noisy at
  60fps. Used by hook cause 5 (excessively flexed = flip). Variance
  form used by inconsistent-contact cause 4.

### Rotation proxies

- **`shoulder_rotation_proxy_at_P7`** — shoulder rotation at
  impact. Used by slice cause 2, pull cause 1, lack-of-distance
  cause 2.

- **`hip_rotation_proxy_at_P7`** — hip rotation at impact. Used by
  hook cause 2, pull cause 4, push cause 1, lack-of-distance cause 2.

### Body positions

- **`head_displacement_P1_to_P7_target_axis`** — head movement from
  address to impact along the target axis (trail-ankle → lead-ankle
  unit vector at P1). Signed: positive = toward target, negative =
  away from target (hanging back). **Validated as primary indicator
  for hanging back** (push cause 5, fat cause 1). Variance form
  used by inconsistent-contact cause 3.

- **`head_vertical_change_P1_to_P7`** — head vertical movement,
  image-y, sign-flipped so raised = positive. Used by thin cause 1
  (raised at impact), thin cause 4 (paired with scoop), shank
  cause 1 (raised as part of early extension), shank cause 4
  (diving toward ball). Variance form used by inconsistent-contact
  cause 3.

- **`hip_displacement_P1_to_P7_target_axis`** — hip midpoint
  movement along target axis. Signed: positive = lateral slide
  toward target, negative = away. No v1 cause primarily depends on
  this; retained for possible v2 use (bump-and-hang faults).

- **`hip_vertical_change_P1_to_P7`** — hip midpoint vertical
  change, image-y, sign-flipped so raised = positive. **Confounded
  by natural hip rotation.** Corroborating indicator only for early
  extension (slice cause 4, push cause 2, fat cause 2, thin cause 1,
  shank cause 1). Do not use as sole indicator.

- **`spine_angle_at_P7`** — spine tilt at impact. Used as the P7
  operand of `spine_angle_change_P1_to_P7`.

### Arm position

- **`trail_elbow_position_at_P4_to_P7`** — derived feature tracking
  trail elbow path through transition. Signed: positive = out
  (over-the-top), negative = under (stuck). Used by slice cause 2,
  hook cause 2, pull cause 1, push cause 1, shank cause 3.
  Five-symptom feature; careful threshold tuning in Phase 3.

  *Not yet built. Belongs to the orchestrator layer or a small
  derived-features extractor — its P4 and P7 inputs come from raw
  trail-elbow keypoints, and the "position" here is a
  target-axis-projected image-space quantity.*

- **`lead_arm_angle_at_P7`** — bend in lead arm at impact
  (chicken-winging). Used by hook cause 4, lack-of-distance cause 6.

- **`hand_distance_from_body_at_P7`** — hand position relative to
  body at impact (compared against `hand_distance_from_body_at_P1`).
  Used by shank cause 5. Noisy from down-the-line.

### Ankle position (flagged as unreliable)

- **`ankle_displacement_at_P7`** — mid-ankle vertical change from
  P1 to P7, image-y, raised = positive. Proxy for "diving onto
  toes." Used by shank cause 4. Flagged as unreliable from
  down-the-line; low-confidence indicator.

---

## P10 features (finish)

- **`hip_rotation_proxy_at_P10`** — hip rotation at the finish.
  Used only via the derived delta `hip_rotation_change_P7_to_P10`.

---

## Delta features (checkpoint-to-checkpoint)

- **`head_displacement_P1_to_P4`** — head movement address-to-top,
  projected onto the target axis. Positive = toward target (reverse
  pivot direction). **Weak primary indicator for reverse pivot**
  (slice cause 5, fat cause 4) — fires only on extreme cases;
  demonstration swing_24 failed direction.

- **`hip_rotation_change_P7_to_P10`** — delta of hip rotation
  proxies (P10 minus P7). Small or negative = body stalled
  (hook cause 4). Computed by the rotation extractor as a delta of
  its own outputs.

- **`spine_angle_change_P1_to_P4`** — change in spine angle from
  address to top. Signed: positive = spine bent more forward at
  top, negative = straightened during backswing. Used by thin
  cause 2 (loss of posture).

- **`spine_angle_change_P1_to_P7`** — change in spine angle from
  address to impact. Signed: positive = spine bent more forward
  at impact, negative = spine straightened. **Primary early-extension
  indicator in v1** (took over from `hip_vertical_change_P1_to_P7`
  which is rotation-confounded). Used across slice cause 4, push
  cause 2, fat cause 2, thin cause 1, shank cause 1.

---

## Whole-swing features (no checkpoint)

- **`tempo_ratio`** — backswing duration (P1 → P4) divided by
  downswing duration (P4 → P7). Used by lack-of-distance cause 4.
  Variance form (`tempo_ratio_stddev`) used by inconsistent-contact
  cause 2.

- **`total_swing_duration`** — total swing time P1 → P10, in
  seconds. Used by lack-of-distance cause 4. Variance form used by
  inconsistent-contact cause 2.

These are the only directly-measured (non-proxy) features in the
KB. Worth giving them appropriate confidence weight when matched.

---

## Variance features (computed across user's 3-5 swings)

Every feature above is expected to have a `_stddev` and `_range`
form computed across the user's uploaded swings by the aggregator.
Used by inconsistent-contact KB entries. Whether both stddev and
range are exposed or only stddev is deferred to Phase 3 KB
authoring.

---

## Feature count summary

- P1 features: **7**
- P4 features: **6**
- P5 features (interpolated): **4**
- P7 features: **8** (excluding `trail_elbow_position_at_P4_to_P7`
  which is not yet built and lives in a derived layer)
- P10 features: **1** (used only via delta)
- Delta features: **4** (head_P1_P4, hip_rot_P7_P10, spine_P1_P4,
  spine_P1_P7)
- Whole-swing features: **2**

**Total distinct schema features: 36.**

Plus per-feature `_stddev` (and optionally `_range`) variants for
inconsistent-contact scoring.

---

## High-leverage features

A few features carry most of the diagnostic weight. If Phase 3 KB
tuning shows problems with any of these, diagnosis quality suffers
materially across multiple symptoms:

- **`trail_wrist_angle_at_P4`** — primary wrist measurement, drives
  slice cause 1 and hook cause 1
- **`spine_angle_change_P1_to_P7`** — primary early-extension
  indicator, appears in 5 causes across 5 symptoms
- **`head_displacement_P1_to_P7_target_axis`** — validated
  hanging-back indicator, appears in push/fat/thin causes
- **`head_vertical_change_P1_to_P7`** — 4 causes across 3 symptoms
  (thin ×2, shank ×2)
- **`trail_elbow_position_at_P4_to_P7`** — 5 causes across 5
  symptoms (once built)
- **`tempo_ratio`** — directly measured, high-confidence
  lack-of-distance indicator

Focus initial threshold-tuning effort in Phase 3 on these.

---

## Features flagged as underspecified

- **`trail_elbow_position_at_P4_to_P7`** — not yet built; formula
  should be a target-axis projection of the trail elbow at P7
  relative to the trail elbow at P4, sign convention: positive =
  outward (over-the-top). Resolve in the orchestrator design or a
  small derived-features extractor.

---

## Features flagged as noisy or unreliable in v1

These features are computed and stored but flagged as low-confidence
in KB matching:

- **`lead_wrist_angle_at_{P1,P4,P7}`** — lead-side visibility
  limits from down-the-line
- **`lead_wrist_angle_at_P7`, `trail_wrist_angle_at_P7`** — motion
  jitter at 60fps
- **`hip_vertical_change_P1_to_P7`** — rotation-confounded
- **`hand_distance_from_body_at_{P1, P7}`** — 19% CV on normal
  baseline
- **`ankle_displacement_at_P7`** — back-foot occlusion from
  down-the-line
- **`stance_width_at_P1`** — horizontal-along-camera-axis
  measurement, noisy but retained

The KB matcher should treat these with reduced confidence weight
and require multi-feature agreement before diagnosing causes that
depend on them.