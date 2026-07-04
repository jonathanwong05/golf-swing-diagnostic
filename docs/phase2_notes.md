# Phase 2 Notes

Running notes on Phase 2 work: feature extraction and aggregation.
This document complements `phase1_notes.md` and records findings,
design decisions, and known limitations as they're discovered.

## Wrist measurement reliability across checkpoints

### What we tested

Compared trail-wrist angle (signed angle from forearm to hand-index
vector) at P4 and P7 across:

- Fault demos: cupped_at_top, bowed_at_top, scoop_at_impact,
  hold_off_at_impact (swings 16-19)
- Normal-swing baselines (swings 09, 15)
- ±5 frame windows around P7 for the scoop and hold-off demos

### What we found

**P4 wrist measurement is reliable.**

- Cupped demo (swing_16) at P4: trail_ang = +51.96°
- Bowed demo (swing_17) at P4: trail_ang = −0.03°
- Separation: ~52°
- Normal swings sit in roughly the +0° to +35° range at P4
- Per-frame values stable; visibility 0.92-0.96 on the trail side

The cupped demo lands clearly above the normal range; bowed lands
clearly below. Trail-side measurement validates the cupped-at-top
indicator with strong signal-to-noise.

**P7 wrist measurement is unreliable.**

- Scoop demo at P7: trail_ang = −4.60°
- Hold-off demo at P7: trail_ang = +3.92°
- Separation: ~8.5°
- ±5 frame window around P7 shows values jumping 30-100° between
  consecutive frames, including on the clean-strike baseline swing
- Visibility itself is acceptable (0.80-0.92 through the window)

The chaos isn't a P7-detection problem. The clean baseline shows
the same pattern: trail_ang at P7 = +5.22°, but with values like
−38° two frames earlier and +11° five frames later. This is motion-
induced jitter in MediaPipe's per-frame landmark tracking — the
hands are moving fast enough at 60fps that individual frame
estimates are noisy.

Windowing (averaging across a frame range) does not fix this
because the noise is per-frame, not per-checkpoint-choice.

### Why the demos themselves under-perform expectations

User note: the scoop and bowed-at-impact demos may have been less
extreme than ideal. The user's natural tendency is cupping, making
bowing harder to demonstrate convincingly. Scoop was unfamiliar as
a feel. Re-filming with more deliberate exaggeration might widen
the separation by 5-10° but does not address the underlying motion-
jitter problem.

### Design response

P4 wrist features remain primary indicators in the KB with full
confidence weight. P7 wrist features are computed and stored in
`SwingFeatures` but treated as low-confidence indicators in KB
matching, alongside the other noisy features flagged in the
features inventory.

Two causes depending on P7 wrist measurement are affected:

- Hook cause 5 (trail hand overactive at impact)
- Thin contact cause 4 (scoop / flip at impact)

Both become harder-to-diagnose in v1 and may more frequently
trigger the "no clear cause detected" fallback. This is correct
behavior given the measurement limits — better to admit uncertainty
than to invent a diagnosis from noisy data.

### v2 considerations

Filming at 120fps or 240fps would reduce per-frame motion blur and
likely produce cleaner landmark tracking through impact. Worth
adding to the v2 considerations list. For v1, the system documents
its limit and degrades gracefully rather than overclaiming.

---

## Rotation measurement design

### The problem

True rotation is a 3D quantity that can't be measured directly from
a single down-the-line camera — the camera is looking along the axis
of rotation. We need a projection-based proxy.

### First design (failed): normalize by horizontal shoulder separation at P1

The initial design took the signed x-separation of paired landmarks
(trail - lead) at each checkpoint and normalized by |P1 x-separation
of the same pair|. Idea: at address the ratio is +1 by construction,
and it varies with rotation from there.

This produced catastrophic outliers. Two of 15 normal swings (02, 14)
happened to have P1 shoulder configurations more parallel to the
camera, giving tiny horizontal separations at address. Every ratio
divided by that tiny denominator was 5-10x larger than in other
swings. Normal-swing stddev on shoulder_rotation_proxy_at_P4 was 2.50
around a mean of −2.40 (CV over 100%). No fault demo landed
meaningfully outside that noise floor.

### The insight

Horizontal separations from a down-the-line view are inherently noisy
because they're measured along the camera's line of sight — any small
change in true rotation or camera angle produces a large change in
the projected separation. Vertical body dimensions, by contrast, are
cleanly projected regardless of rotation.

### Empirical check across 15 normal swings

Compared six candidate reference lengths at P1:

| reference               | mean   | stddev | CV     |
|-------------------------|--------|--------|--------|
| ankle_stance_horiz      | 0.0435 | 0.0041 | 9.35%  |
| hip_stance_horiz        | 0.0512 | 0.0159 | 31.05% |
| shoulder_stance_horiz   | 0.0838 | 0.0276 | 32.91% |
| **ankle_to_hip_vert**   | 0.1902 | 0.0131 | **6.86%** |
| hip_to_shoulder_vert    | 0.1380 | 0.0120 | 8.68%  |
| ankle_to_shoulder_vert  | 0.3282 | 0.0247 | 7.52%  |

Vertical body dimensions have 3-4x tighter distributions than
horizontal separations, as predicted. Ankle-to-hip vertical is the
tightest and has good absolute magnitude for ratio dynamic range.

### Final design

Normalize signed (trail.x - lead.x) at each checkpoint by
ankle-to-hip vertical distance at P1. Details in
`src/golf_diagnostic/features/extractors/rotation.py`.

### Validation results

Normal-swing distributions become tight:
- shoulder_rotation_proxy_at_P4: mean −0.70, stddev 0.03 (4% CV)
- hip_rotation_proxy_at_P4: mean −0.40, stddev 0.02 (5% CV)
- hip_rotation_proxy_at_P10: mean +0.44, stddev 0.01 (2% CV)

Fault demos separate cleanly for large differences:
- swing_25 (short_backswing) at hip_rotation_proxy_at_P4: z = +4.44
- swing_25 shoulder_rotation_proxy_at_P4: z = +3.37

Weaker separation for subtle at-impact differences (e.g., over-the-top
shoulder position at P7 gives z = 0.61). Consistent with the wrist
finding: measurement is easier at static top-of-backswing than at
fast-moving impact.

### Incidental fault-demo drift

All three rotation-related fault demos (over_the_top, stuck_inside,
short_backswing) showed reduced backswing rotation vs. normal swings,
not just the short_backswing demo. The user unconsciously shortened
the backswing while focusing on the demonstrated fault. This is
expected demo-artifact behavior, not a measurement issue.
Documented in the fault-demo spec's "incidental drift is acceptable"
note; validation logic should not assume other features remain at
baseline when a specific fault is demonstrated.

---

## Posture extractor

### Went smoothly, one architectural note

Extractor implementation was straightforward: interior joint angles
for knees and lead arm (using `angle_at_joint` from primitives), and
angle-from-vertical for the spine (using mid-hip to mid-shoulder
vector).

Empirical validation on 15 normal swings + 4 fault demos:
- Absolute values are physiologically plausible (spine 30-40°, knee
  flex 135-165°, lead arm 170°).
- Normal-swing distributions have reasonable spread (spine at P1
  stddev ~4°, lead arm stddev ~6°).

### The session-offset finding

All four fault demos showed spine_angle_at_P1 5-9° higher than the
normal-swing mean. This wasn't a fault signal — it was a session-
level address-posture offset from filming the demos in a different
session than the normal swings. The raw spine_angle_at_P7 z-scores
were therefore misleading.

### Response: added delta features to the schema

Added `spine_angle_change_P1_to_P4` and `spine_angle_change_P1_to_P7`
as explicit schema fields, computed as simple subtractions in the
extractor. These deltas cancel session offsets cleanly — normal-swing
distributions center near zero with stddev 3-4°, while session-level
offsets don't appear at all.

Pattern for future extractors: any feature where session-level offsets
could confound absolute values should also have a delta version in
the schema, computed at extractor time. This matches how head and
hip displacements are already defined (as deltas).

### One counterintuitive validation result

The `early_extension` demo (swing_23) did NOT show up as an outlier
on `spine_angle_change_P1_to_P7` — its delta was −2.77°, inside the
normal range. Meanwhile the `stuck_inside` demo (swing_21) showed a
strong outlier (−11.92°, z = −2.49).

Two lessons:

1. "Early extension" is a compound cause with multiple biomechanical
   signatures (hip thrust vs spine straightening vs head lift). This
   particular demo happened to be hip-driven and not spine-dominant.
   The KB should combine multiple indicators for this cause rather
   than relying on any single feature.
2. Fault demos have unintended side effects. The stuck-inside demo
   included substantial spine straightening that wasn't the focus
   of the demo. This is the same "incidental drift" pattern already
   documented for rotation.

### Swings under mild suspicion

- swing_11 shows spine_angle_change_P1_to_P7 = −12.28° in the
  "normal" bucket. Either your normal swing 11 genuinely early-
  extends, or MediaPipe had a bad frame on the shoulder/hip
  midpoint at P7. Not blocking, but worth being aware of when
  interpreting cross-swing baselines.

---

## Position extractor — design (head and hip displacement splits)

The single `head_displacement_P1_to_P7` and `hip_displacement_P1_to_P7`
fields in the original schema conflated two diagnostically distinct
axes. Target-axis motion diagnoses hanging back (head) and lateral
slide (hip). Vertical motion diagnoses standing up / diving into the
ball (head) and early extension (hip). These are different faults
with different fixes, and a single scalar can't carry both signals.

Split into four fields total:
- `head_displacement_P1_to_P7_target_axis`
- `head_vertical_change_P1_to_P7`
- `hip_displacement_P1_to_P7_target_axis`
- `hip_vertical_change_P1_to_P7`

`head_displacement_P1_to_P4` is not split — no v1 cause uses head
vertical at the top of the backswing.

Target axis is resolved per-swing at P1 as the unit vector from
trail-ankle to lead-ankle. All target-axis displacements are dot
products against this vector. Vertical features are image-y with
the sign flipped so "raised" reads positive, matching diagnostic
intuition. If either ankle at P1 has low visibility, target-axis
features return NaN on that swing; vertical features are unaffected.

---

## Position extractor — validation results (n=15 normal baseline)

Structurally correct, all features produce finite values across the
15-swing normal set and all 15 fault-demo swings. One of four
targeted fault demos cleanly caught by this extractor alone
(hanging_back, z=−1.24). The others fail for reasons that are
mostly not the extractor's fault.

**`hanging_back` (swing_22): validated.** `head_displacement_P1_to_P7_target_axis`
= −0.094 vs baseline mean −0.024, z=−1.24. Direction correct,
magnitude meaningful. The target-axis projection based on
trail-ankle → lead-ankle is working.

**`early_extension` (swing_23): fails, and the extractor is not to blame.**
`hip_vertical_change_P1_to_P7` = 0.059 vs baseline mean 0.098. The
demo shows *less* upward hip motion than a typical normal swing, which
is the opposite of what early extension should look like. Root cause:
hip vertical change is confounded by natural hip rotation. When hips
rotate open through impact, the mid-hip point rises in image space by
5-15% of body-height regardless of whether the player is early-
extending. This means "hip rising" is a normal-swing baseline signal,
not a fault indicator.

Design consequence: **do not treat `hip_vertical_change_P1_to_P7` as
the primary early-extension indicator in the KB.** The primary should
be `spine_angle_change_P1_to_P7` (from posture extractor), which is
delta-based and unconfounded by rotation. `hip_vertical_change_P1_to_P7`
is a corroborating indicator at best. This is a KB-design update,
not an extractor bug — the feature measures what it claims to
measure, but what it measures is less diagnostic than the causes
catalog assumed.

**`reverse_pivot` (swing_24): fails; likely demo issue.**
`head_displacement_P1_to_P4` = −0.057 (head moved away from target)
vs expected positive (head moved toward target). Two possibilities:
(a) the demo didn't produce a clean reverse pivot despite the intent,
or (b) shoulder rotation carried the head trail-ward faster than the
pivot could carry it target-ward.

Following the weight-distribution drop (below), `head_displacement_P1_to_P4`
becomes the primary reverse-pivot indicator in v1 — but marked "weak"
in the confidence vocabulary. Reverse pivot is expected to fire only
on extreme cases in v1, with the "no clear cause detected" fallback
handling the rest.

**`standing_too_close` (swing_28): fails, marginal.**
`hand_distance_from_body_at_P1` = 0.464 vs baseline mean 0.487, only
5% below baseline (z=−0.25). Feature baseline CV is 0.19 — meaningful
noise in the perpendicular-distance-to-torso-axis measurement, likely
from the shoulder-hip line reference itself having variability. KB
threshold for this feature should be conservative; expect
low-confidence detection of mild "standing too close" and reliable
detection only of extreme cases.

### Verdict

Position extractor produces correct, stable measurements with no
NaN pollution. Diagnostic power varies by feature:

- `head_displacement_P1_to_P7_target_axis` — validated as clean signal
- `hip_vertical_change_P1_to_P7` — confounded, corroborating only
- `head_displacement_P1_to_P4` — weak but retained as best available
- `hand_distance_from_body_at_P1` — real signal but noisy, needs
  conservative thresholds
- Other features (stance_width, ankle_displacement) — computed
  honestly, KB will downweight per features_inventory notes

No further work needed on this extractor.

---

---

## Rotation extractor — hip_rotation_change_P7_to_P10 delta

Added `hip_rotation_change_P7_to_P10` to the rotation extractor as a
delta feature, computed as `hip_rotation_proxy_at_P10 −
hip_rotation_proxy_at_P7`. This closes a schema loose end — the
field was defined in `SwingFeatures` but not produced by any
extractor. Matches the delta pattern established in the posture
extractor for spine deltas.

Follows locked-in principle 4: the delta cancels session-level
offsets in the raw proxies and gives a cleaner signal than either
operand alone.

### Validation results (n=15 normal baseline)

Normal-swing distribution: mean +0.62, stddev 0.05, range +0.51 to
+0.72. CV ~8%, tighter than either raw proxy individually
(hip_rotation_proxy_at_P7 has stddev 0.06 on a mean of −0.18;
hip_rotation_proxy_at_P10 has stddev 0.01 on a mean of +0.44). The
tightness of the delta comes from P7 and P10 hip rotation being
positively correlated within a golfer — a swing with slightly more
rotation at impact also has slightly more at finish, so much of the
per-swing noise cancels in the subtraction.

No negative or near-zero values across any normal swing. The
"healthy rotation through impact to finish" signal has a clean
baseline.

### Fault-demo readings

All three non-stall fault demos land inside the normal band:

- swing_20 (over_the_top): +0.59, z=−0.70
- swing_21 (stuck_inside): +0.68, z=+1.13
- swing_25 (short_backswing): +0.65, z=+0.62

This is the correct behavior. None of these demos intrinsically
involves stalling P7→P10 rotation — over-the-top and stuck-inside
are transition-path faults; short-backswing is a P4 range-of-motion
fault. Body-stall-through-impact (hook cause 4) is a distinct fault
we haven't demonstrated yet.

### Confidence label

`hook cause 4` uses this feature as its primary indicator. Label:
**plausible**. Geometry is correct, baseline is well-behaved, and
the non-stall demos correctly do not fire — but there's no positive
validation demo confirming the feature moves in the expected
direction on a real body-stall swing. A body-stall demo would
convert this to `validated`; deferred until such a demo is filmed.

## Weight distribution proxy — dropped from v1

Attempted to build a `weight_distribution_proxy_at_{P1, P4, P7}`
extractor producing three features via `(mid_hip - mid_ankle)`
projected onto the P1 target axis, normalized by ankle-to-hip vertical.

Empirical result on the 15-swing normal set + 15 fault demos:
- All 45 values sat in a range of 0.83 to 1.07
- CV across normal swings: 0.06 (P1), 0.08 (P4), 0.06 (P7)
- Reverse pivot demo caught direction-wise (z=+1.13) but the
  "signal" was 0.965 vs. baseline mean 0.889, a difference well
  inside the range every non-faulty swing occupied
- Hanging back demo failed direction (weight at P7 was +1.04, above
  baseline mean, when it should have been below)

Diagnosis: the measurement is nearly tautological in down-the-line
view. The target axis (trail-ankle to lead-ankle at P1) projects to
a near-zero image-x magnitude because the two ankles are foreshortened
along the camera axis. After normalization, the ratio becomes
approximately "how vertical is the hip-above-ankle vector relative to
itself" — a quantity that is trivially ~1.0 for any human standing on
their feet.

Weight distribution is a horizontal-lateral measurement along the
axis of the target line. In down-the-line view that axis is aligned
with the camera's line of sight, and the camera can't see motion
along its own axis. The measurement is not just noisy — it's
structurally invisible from this angle.

Design consequence: the three weight-distribution features are
removed from v1. Schema goes from 42 fields to 39. Three catalog
entries lose their primary indicator:

- **Reverse pivot**: primary was `weight_distribution_proxy_at_P4`;
  now falls back to `head_displacement_P1_to_P4` (position extractor,
  weak on swing_24 demo)
- **Hanging back**: primary was `weight_distribution_proxy_at_P7`;
  the secondary indicator `head_displacement_P1_to_P7_target_axis`
  becomes primary (already validated cleanly, z=−1.24 on swing_22)
- **Lack of distance cause 5 (no ground use)**: dropped from v1
  entirely; lack-of-distance still has five other causes

Do not re-attempt weight measurement from down-the-line view.
Weight distribution requires either face-on video (a v2 concern)
or actual force-plate data (out of scope entirely). This is the
first instance of the "invisible axis principle" now formalized in
`docs/measurement_visibility_decisions.md`.

---

## Grip strength (lead_hand_knuckle_visibility_at_P1) — dropped from v1

Same principle as weight distribution: dropped without an implementation
attempt because the geometry doesn't support the measurement.

Three stacked failure modes:
1. MediaPipe pose landmarks treat the hand as four loose points
   (wrist, pinky, index, thumb) — not true hand keypoints. Grip
   strength requires knuckle-level detail we don't have.
2. Lead hand in down-the-line view is on the far side of the body;
   pinky and index visibility typically 0.15-0.40, below the 0.5
   threshold used elsewhere.
3. Grip strength is rotational around the shaft axis, which points
   roughly along the camera axis at address — the axis we're blind to.

Schema field count 39 → 38. Two catalog causes dropped from v1:
slice cause 3 (weak grip), hook cause 3 (strong grip). Both were
already low-confidence.

---

## Setup alignment (shoulder_line_at_P1, hip_line_at_P1) — dropped from v1

Attempted to build both features as the signed 2D angle between the
paired-shoulder / paired-hip vector and the paired-ankle vector at P1.
Feet, shoulders, and hips are all visible landmarks, so the extractor
computes cleanly.

Empirical result on the 15-swing normal set + 15 fault demos:

- `shoulder_line_at_P1`: mean +67.14°, sd 60.79°, range [−90.5°,
  +104.6°]
- `hip_line_at_P1`: mean +58.44°, sd 39.99°, range [−67.9°, +89.7°]
- Values sitting near ±90° across nearly every swing, with sign
  flips (swings 02, 14, 17, 18 negative; most others positive)

The mean of +67° with sd of 61° isn't noise around a real angle. It's
what you get when the measurement is unstable around a singularity.

Diagnosis: the foot line at P1 in down-the-line view is nearly along
the camera axis. Both ankles project to almost the same image-x, so
the (lead_ankle − trail_ankle) vector's image-space direction is
dominated by a tiny y-difference between the ankles (perspective:
the far foot projects slightly higher than the near foot). The foot
vector's image direction ends up near-vertical, dominated by camera
height rather than by how the feet are actually oriented.

The shoulder line has real horizontal spread in image space (shoulders
are wider than the foot separation the camera sees, and less
foreshortened). Its image direction is near-horizontal.

Angle between a near-vertical vector and a near-horizontal vector:
~90°. And when tiny pixel-level variation flips which ankle projects
slightly higher, the sign of the foot vector flips too, taking the
computed angle with it. That's the ±90° sign-flipping pattern in the
data.

This is the same failure mode as weight distribution: the reference
axis we tried to project against is itself along the invisible
(camera) axis. It carries no target-line information. And unlike
weight distribution — where the math collapsed to a boring near-
constant — the angle computation collapses to a chaotic
sign-flipping ±90° pattern, which is worse.

Design consequence: both features removed from v1. Schema field
count 38 → 36. Two catalog causes dropped:

- **Pull cause 2 (aim left)** — was to depend on
  `shoulder_line_at_P1` aimed toward lead side
- **Push cause 3 (aim right)** — mirror direction

Both were already flagged as low-confidence indicators. This is the
second instance of the invisible-axis principle in action; combined
with the weight and grip drops, we now have three separate features
that failed the same way, motivating the formal rule in
`docs/measurement_visibility_decisions.md`.

---

## Locked-in principles for the rest of Phase 2 and beyond

Five principles that have emerged from Phase 2 empirical work.
These constrain future feature design and are not to be relitigated
without new evidence.

1. **Trail-side is primary for wrist measurements from down-the-line.**
   Documented in `docs/measurement_visibility_decisions.md` (Rule 1).
   Do not switch back.

2. **Normalize by ankle-to-hip vertical distance at P1**, not any
   horizontal quantity. The vertical body dimension projects cleanly
   from down-the-line; horizontal ones are foreshortened along the
   camera axis. This rule holds for rotation, position, and any
   future feature needing a body-scale reference.

3. **If the geometry doesn't support the measurement, drop the
   feature — don't produce placeholder values.** The three drops
   this phase (weight, grip, alignment) all obey this rule.
   Formalized as the "invisible axis principle" in
   `docs/measurement_visibility_decisions.md` (Rule 2).

4. **Delta features cancel session-level offsets.** Used in posture
   (spine); consider for future features where absolute values may
   drift across sessions.

5. **Absence of signal on the invisible axis.** Weight distribution,
   grip strength, and alignment all fail for the same underlying
   reason — the signal we want is defined relative to (or rotates
   around) the target line, which IS the camera axis in down-the-line
   view. Any feature with this property is unbuildable in v1.

---

## v2 candidates (out of scope for v1, worth noting)

- **Face-on camera view** — would restore weight, alignment, and
  grip measurements. Would also restore lead-side wrist visibility.
- **120+ fps filming** — would potentially restore reliable P7
  wrist measurement.
- **Real P5 detection** (instead of P4/P7 interpolation) — would
  strengthen casting-related causes across fat, thin, and
  lack-of-distance symptoms.
- **P2/P3/P5/P6/P8/P9 detection** — full checkpoint coverage.

---

## Tempo extractor

Two features, no landmarks: `tempo_ratio` (backswing frames /
downswing frames) and `total_swing_duration` (P10−P1, in seconds).
Fps threaded through as an optional kwarg on `extract()` per Option D
of the signature discussion; unused by all other extractors, which
will ignore it in the orchestrator's uniform dispatch.

### Validation results (n=15 normal baseline)

- `tempo_ratio`: mean 2.01, stddev 0.35, range 1.67-2.93
- `total_swing_duration`: mean 1.45s, stddev 0.34s, range 1.05-2.29s

### The tempo_ratio 2.0 vs 3.0 question

Golf-tempo literature and the causes catalog both reference ~3:1 as
neutral iron tempo. This dataset's baseline sits closer to 2:1. Two
plausible explanations, likely both contributing:

1. The user's natural iron tempo may genuinely be quicker than tour
   average. Amateur ratios of 2:1 are not unusual.
2. Phase 1's documented ~3-5 frame P1 late-bias systematically
   shortens measured backswing duration while leaving downswing
   unchanged, dragging the measured ratio below true.

Not resolved here. Phase 3 threshold tuning uses the empirical
baseline, not textbook numbers — "slow tempo" for this user means
outside their own 2.01 ± 0.35 band, not below 3.0.

### Universal fault-demo drift on tempo_ratio

All three rotation-fault demos (over_the_top, stuck_inside,
short_backswing) landed at z < −1.5 on tempo_ratio despite none
being intended as tempo demos. Every fault demo rushed the
backswing more than it rushed the downswing, dragging the ratio
down. This is the same incidental-drift phenomenon documented for
rotation and posture — demonstrated aggressive moves come with
compressed backswings whether the user intends it or not.

Design consequence: fault-demo z-scores on tempo_ratio should be
treated skeptically. Any future fault demo z-scoring against this
baseline will show tempo drift as a side effect.

### Confidence label

`lack of distance cause 4` (slow tempo / wrong rhythm) uses these
features as primary indicators. The causes catalog originally
labeled this cause `validated` on the strength of tempo being
directly measured. Downgrade to `plausible`: no slow-tempo demo
has confirmed the feature fires correctly in the expected direction.
Incidental drift shows features move for *rushed* swings on
non-tempo demos, which is the wrong signal for validation.
Consider filming a deliberate slow-tempo demo to close this out.

### Structural note

`total_swing_duration` on swing_03 = 2.29s, close to the "P10
fell back to last-frame" red-flag threshold of 2.5s. Clip is
genuinely 27fps × 62 frames, so the duration is real, not a
segmentation artifact — but worth remembering swing_03 has a
long held finish if it appears as an outlier on other features.

---

## Interpolated P5 extractor

Four features at frame midpoint between P4 and P7: lead/trail wrist
angle, lead arm to torso angle, and hand path proxy (hand-distance
delta P4 -> P5). Chose Option B (measure at interpolated frame) over
Option A (arithmetic mean of P4 and P7 values) because casting is a
"release happens early" signal and Option A dilutes it with the
neutral P7 value; Option B preserves whatever the wrist actually
did at the midpoint frame.

### Validation results (n=15 normal baseline)

Structural sanity clean: all 20 swings produce finite values, all
structural checks pass.

- `lead_wrist_angle_at_P5_proxy`: mean 33.6°, stddev 12.7°, range
  12.3-60.6° — still cupped as theory predicts, since release
  hasn't happened by frame midpoint.
- `trail_wrist_angle_at_P5_proxy`: mean -5.1°, stddev 20.0°, range
  -43.6 to +27.8° — noisy, motion jitter dominates.
- `lead_arm_to_torso_angle_at_P5_proxy`: mean 39.4°, stddev 10.4°,
  range 22.5-54.4° — tight, physically sensible.
- `hand_path_proxy_at_P5_proxy`: mean -0.25, stddev 0.10, range
  -0.42 to -0.13. All 15 normal swings negative.

### Wrist measurement side flip at P5

At P5 the lead-primary/trail-corroborating rule REVERSES from the
P4/P7 convention. Empirical: normal-swing stddev is 12.7° on the
lead side vs. 20.0° on the trail side. Trail-side motion jitter at
mid-downswing exceeds the visibility-limited noise on the lead side.
For casting causes (fat 3, thin 3, distance 3), the KB should treat
`lead_wrist_angle_at_P5_proxy` as primary and `trail_wrist_angle_at_P5_proxy`
as corroborating only. Coaching language remains in lead-wrist terms
(no translation needed since measurement is already lead-side).

### hand_path_proxy is uniformly negative — feature captures wrong phase

All 15 normal swings show negative hand_path_proxy at P5 (hands moving INWARD from P4 to P5). This is diagnostically correct behavior — a normal downswing "drops the club into the slot" with hands traveling closer to the body before releasing outward through impact.
The over_the_top demo (swing_20) came in at −0.41, more negative than the normal mean, not positive as the causes_catalog premise assumed. Cross-checking swing_20 against other extractors confirms it IS a valid over-the-top demo (shoulder_rotation_proxy_at_P7 = +0.09, z = +2.3 in the open direction). The issue is with the feature definition, not the demo: the outward-hand-move component of over-the-top happens after P5, not during the P4→P5 window. Trail elbow flies out at P4→P5, but hands themselves drop into the slot in that window on all swings.
Design consequence: label shank cause 3 confidence as weak. Consider redesigning in v2 as a P4→P6 or P4→P7 hand-distance delta, or as a trail-elbow-position delta rather than hand-position delta (trail elbow is what actually moves outward at P5 in OTT).


### Wrist demos partially validate lead_wrist_angle_at_P5_proxy

Cupped demo (swing_16) at P5: lead_wrist = 54.09°, z = +1.61. Direction
correct — a persistent-cup swing stays cupped at midpoint. This is
the diagnostic pattern casting looks for (only inverted — casting
would show LOW P5 wrist angle after starting at typical P4). Not a
casting demo, but suggests lead_wrist_angle_at_P5_proxy would move
in a detectable direction for a real casting demo.

Bowed demo (swing_17) at P5: lead_wrist = 32.6° (baseline). Same
"bowed demo doesn't produce clean bowing" observation as documented
in the wrist extractor validation.

### Universal fault-demo drift on lead_arm_to_torso

Three fault demos all show reduced lead-arm-to-torso angle
(swing_20: z=-1.59, swing_21: z=-1.33, swing_25: z=-3.51). None of
these was a connection-fault demo. Same incidental-drift phenomenon
as rotation, posture, and tempo — aggressive/demonstrated moves
come with tighter connection to the body. Fault-demo z-scores on
this feature should be treated skeptically until a real
arm-disconnect demo is filmed.

### Confidence labels

- `lead_wrist_angle_at_P5_proxy` — plausible (baseline reasonable,
  cupped demo validates direction; no casting demo yet)
- `trail_wrist_angle_at_P5_proxy` — weak (motion-jitter noisy)
- `lead_arm_to_torso_angle_at_P5_proxy` — plausible (clean baseline,
  no shank/connection demo yet)
- `hand_path_proxy_at_P5_proxy` — weak (over_the_top demo went the
  wrong direction; may need redesign)

### Deferred work

- Film a casting demo to validate lead_wrist_angle_at_P5_proxy
  moves in the expected direction (low value, near neutral at P5).
- Consider redesigning hand_path_proxy to use a wider frame window
  (P4->P7 or a P6 checkpoint if added) so it captures the outward
  hand move that happens after P5.

  ---

## Orchestrator

Single function `compute_swing_features` runs all six extractors on
one swing and returns a merged `SwingFeatures`. Design choices
detailed in `docs/module_interfaces.md`:

- Module-level dispatch table pairs each extractor with a per-pose
  kwargs function. Only `TempoExtractor` needs anything beyond the
  standard trio (it needs `fps`). Extending is one line.
- Import-time schema coverage check: `∪ FEATURES == FEATURE_NAMES`
  exactly. A schema field with no producer, an unknown feature name,
  or a duplicate producer fails loud on module import rather than
  silently returning NaN. This is exactly the class of bug that
  `hip_rotation_change_P7_to_P10` was — the schema had the field,
  no extractor produced it, and nothing caught it until manual
  audit.
- Aggregation across swings is not the orchestrator's concern. The
  caller runs `compute_swing_features` per swing and passes the
  list to `schema.aggregate`.

### Validation results

Ran on all 30 swings in the dataset. Every field on every swing
populated — zero NaN counts across the full 30 swings × 36 features
= 1,080 field-population matrix. This is stronger than expected;
had anticipated some NaN counts from occasional ankle-visibility
drops affecting target-axis features. The dataset is clean enough
that no extractor's defensive NaN paths were triggered on any
swing.

Cross-check confirmed orchestrator output matches per-extractor
standalone output exactly (no accidental transformations in the
merge). Invalid-input paths (missing checkpoints, bad ordering)
raise ValueError with informative messages.

---

## Phase 2 validation results

End-to-end validation via `scripts/validate_features.py` against
`data/labels.yaml`. Baseline: 15 normal swings. Fault demos: 13
labeled (swings 16-28), 2 deferred (swings 29-30, ball position;
require v2 ball detection).

### Cleanly validated features (5)

The following features produced z >= 1.0 in the expected direction
on their labeled fault demos:

- `trail_wrist_angle_at_P4` — cupped_lead_wrist_at_top demo z=+2.89
- `lead_wrist_angle_at_P4` — cupped_lead_wrist_at_top demo z=+3.60
- `head_displacement_P1_to_P7_target_axis` — hanging_back demo z=-1.24
- `shoulder_rotation_proxy_at_P4` — short_backswing demo z=+3.37
- `hip_rotation_proxy_at_P4` — short_backswing demo z=+4.44

These correspond to five KB causes with `validated` confidence
labels: cupped lead wrist at top (slice cause 1), hanging back
(push/fat causes), insufficient body rotation (lack of distance
cause 1).

### Weak signals — feature direction correct but magnitude small (5)

Features moved in the labeled direction but with |z| < 1.0. Not
regressions; documented as demo-execution or feature-intrinsic
limitations:

- `trail_wrist_angle_at_P4` on bowed_lead_wrist_at_top (swing_17):
  z=-0.41. Bowing is difficult to demonstrate cleanly for a golfer
  whose natural tendency is cupping; already noted in wrist-
  extractor validation.
- `lead_wrist_angle_at_P4` on bowed (swing_17): z=-0.01. Same reason.
- `shoulder_rotation_proxy_at_P7` on over_the_top (swing_20): z=+0.61.
  Direction correct; the real primary indicator will be
  `trail_elbow_position_at_P4_to_P7` once built.
- `spine_angle_change_P1_to_P7` on early_extension (swing_23):
  z=-0.11. Documented as hip-driven-not-spine-dominant demo. Real
  early-extension KB scoring will need multi-indicator combinations
  to catch this variant.
- `tempo_ratio` on rushed_transition (swing_27): z=-0.45. Same
  demo-execution issue as swing_26 below — user's natural tempo is
  already fast, making a "rushed" demo hard to distinguish from
  baseline.

### Feature-intrinsic weak indicators (10 checks, all known_weak)

All 8 P7 wrist checks (across swings 16-19) failed, as predicted.
Motion jitter at 60fps dominates over demo signal; documented in
wrist-extractor validation as unfixable at current framerate.
Requires 120+fps filming to re-attempt.

`head_displacement_P1_to_P4` on reverse_pivot (swing_24) failed
direction (z=-2.04). Feature is documented as `weak` confidence in
the causes catalog — the pose-visible fallback for reverse pivot
after weight_distribution_proxy dropped. Head can drift trail-ward
due to shoulder rotation even during a correct pivot, so the
feature's diagnostic power is limited to extreme cases.

`hand_distance_from_body_at_P1` on standing_too_close (swing_28)
came in WEAK z=-0.25. Feature has 19% baseline CV, needs
conservative KB thresholds.

### Demo-execution gaps (1 unexpected FAIL)

`total_swing_duration` on slow_tempo (swing_26): z=-0.26. User's
"slow" demo produced a duration of 1.36s vs baseline mean 1.45s —
slightly *faster* than average. Combined with the WEAK on the
rushed_transition demo (swing_27), the pattern suggests the user's
natural tempo sits toward the fast end of typical amateur tempo
(baseline mean 2.01 well below the 3:1 tour norm), making both
"slow" and "rushed" demos difficult to distinguish from the user's
already-fast baseline.

Not a feature regression. Documented gap; re-filming with more
deliberate exaggeration or accepting that tempo features are
structurally validated only (direct measurement, no per-swing fault
demo) both work for v1. Not blocking Phase 2 completion.

### Two structural-only validations

`stuck_inside` (swing_21) marked `deferred` — the current schema has
no clean primary indicator for this fault; hip_rotation_proxy_at_P7
direction depends on which stuck-mechanism the demo uses (hips-
outracing-arms vs hold-hips-and-drop-elbow). Awaits
`trail_elbow_position_at_P4_to_P7` in a future derived-features layer.

`ball_position_*` (swings 29-30) marked `deferred` — require ball
detection which is v2 scope.

### Regression-detection status

The validation script serves as an end-to-end regression check going
forward: extractor changes, orchestrator changes, or schema changes
that break previously-validated features will surface immediately
in the aggregate counts. Current exit code 1 is due to the tempo
demo-execution gap alone.