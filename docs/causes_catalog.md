> **Phase 2 update: trail-side wrist features as primary indicators.**
>
> Several entries below — "Cupped lead wrist at top," "Bowed lead
> wrist at top," "Scooping / flipping at impact," "Trail hand
> overactive at impact," "Casting / early release" — list
> `lead_wrist_angle_*` features as primary indicators. For the v1
> down-the-line implementation, the trail-side equivalents
> (`trail_wrist_angle_*`) are the primary measurement with full
> confidence weight; the lead-side versions are low-confidence
> corroborating indicators.
>
> Cupped lead wrist at the top is geometrically paired with extended
> trail wrist at the top; bowed lead pairs with flexed trail; scooping
> (cupped at P7) pairs with extended trail at P7. The mechanic is
> identical; the measurement is just taken from the more visible side.
>
> See `docs/measurement_visibility_decisions.md` for the design rule.
> Coaching language remains in lead-wrist terms throughout the user-
> facing output.

> **Phase 2 update: causes dropped from v1 due to the "invisible axis" principle.**
>
> Five causes below have been dropped from the v1 KB because their
> primary indicators depend on measurements that cannot be extracted
> from down-the-line 2D pose. Each dropped entry is marked
> `[DROPPED FROM v1 — see note]` with a brief explanation. See
> `docs/measurement_visibility_decisions.md` for the full principle.
>
> - Slice cause 3 (weak grip)
> - Hook cause 3 (strong grip)
> - Pull cause 2 (aim left)
> - Push cause 3 (aim right)
> - Lack-of-distance cause 5 (no ground use)
>
> Additionally, three causes had their primary indicator swapped:
> - **Early extension**: primary is now `spine_angle_change_P1_to_P7`
>   (`hip_vertical_change_P1_to_P7` is rotation-confounded and demoted
>   to corroborating)
> - **Hanging back**: primary is now `head_displacement_P1_to_P7_target_axis`
>   (was `weight_distribution_proxy_at_P7`, now dropped)
> - **Reverse pivot**: primary is now `head_displacement_P1_to_P4`
>   (was `weight_distribution_proxy_at_P4`, now dropped). This
>   indicator is WEAK — see confidence vocabulary below.

> **Phase 2 update: confidence vocabulary for causes.**
>
> Each cause is now labeled with one of three empirical confidence
> levels reflecting how well the primary indicator was validated in
> Phase 2 testing:
>
> - **validated** — feature was tested on a fault demo and moved in
>   the expected direction with meaningful magnitude
> - **plausible** — feature measures the correct geometry, but wasn't
>   confirmed on a demo (either because we don't have one or because
>   the demo didn't produce the fault cleanly)
> - **weak** — feature is the best we have but wasn't validated and
>   may not fire reliably; kept because the alternative is dropping
>   the cause entirely
>
> Phase 3 KB authoring will convert these labels into concrete
> `confidence_weight` numbers (validated ≈ 1.0, plausible ≈ 0.7,
> weak ≈ 0.4). Values are subject to tuning.

---

## Body-driven causes

### Early extension  [confidence: plausible]

**Definition:** Hips thrust toward the ball during the downswing;
spine straightens; body height rises from address to impact.

**Primary indicators:**
- `spine_angle_change_P1_to_P7` (negative = spine straightened;
  primary indicator, delta-based so unconfounded by session-level
  offsets)

**Corroborating indicators:**
- `hip_vertical_change_P1_to_P7` (positive = hips raised — but
  confounded by natural hip rotation, so low weight)
- `head_vertical_change_P1_to_P7` (positive = head raised — varies
  by golfer; some players lower head even while early-extending)

**Appears in:**
- Slice (cause 4) — produces face-open compensation
- Push (cause 2) — produces stuck-and-held compensation
- Fat contact (cause 2) — body rises, arms over-compensate → too far down
- Thin contact (cause 1) — body rises, arms don't compensate enough → too high
- Shank (cause 1) — body brings hosel to ball

**Consistency check:** This is the most-shared cause in the KB.
Thresholds for `spine_angle_change_P1_to_P7` should be identical
across all five symptom files. Highest-leverage cause to get right.

---

### Reverse pivot / failed weight shift to trail side  [confidence: weak]

**Definition:** Weight stays on or moves to lead side during
backswing; head moves toward target at the top instead of staying
centered or moving slightly away.

**Primary indicator (v1 fallback):**
- `head_displacement_P1_to_P4` (positive = head moved toward target)

**Note on confidence:** This was originally to be diagnosed via
`weight_distribution_proxy_at_P4`, which is dropped from v1
(down-the-line view cannot measure weight distribution reliably).
Head displacement is the pose-visible fallback but is noisy — the
head can drift trail-ward due to shoulder rotation even during a
correct pivot. The reverse-pivot fault demo (swing_24) failed
direction. Expect this cause to fire only on extreme cases in v1
and to hit the "no clear cause" fallback more often than the other
body-driven causes.

**Appears in:**
- Slice (cause 5) — produces steep, out-to-in downswing
- Fat contact (cause 4) — downswing starts with weight moving backward

---

### Hanging back / failed weight shift to lead side through impact  [confidence: validated]

**Definition:** Weight stays on trail foot through impact; head
ends up behind where it was at address.

**Primary indicator:**
- `head_displacement_P1_to_P7_target_axis` (negative = head moved
  away from target)

**Note on confidence:** Validated on swing_22 fault demo (z=−1.24
in expected direction). Was originally to be paired with
`weight_distribution_proxy_at_P7` as a two-indicator combo; weight
distribution is dropped in v1 but head displacement carries the
signal cleanly on its own.

**Appears in:**
- Push (cause 5) — produces upward-and-rightward path at impact
- Fat contact (cause 1) — low point stays behind ball
- Thin contact (cause 4, partial) — paired with scooping hands

**Consistency check:** Distinct from reverse pivot — reverse pivot
is about weight at the top of the backswing; hanging back is about
head/weight at impact. A player can have one without the other.

---

### Loss of posture / standing up through the swing  [confidence: plausible]

**Definition:** Spine straightens gradually throughout the swing
without specific hip thrust toward ball.

**Primary indicators:**
- `spine_angle_change_P1_to_P4` (negative = straightened during backswing)
- `spine_angle_change_P1_to_P7` (negative = straightened by impact)

**Appears in:**
- Thin contact (cause 2)

**Consistency check:** Overlaps mechanically with early extension.
Kept separate in the thin-contact KB because the discriminator is
where the height is lost (hips-forward vs spine-straightening alone).
Phase 3 will reveal whether this distinction holds up in practice
or whether the two causes collapse.

---

## Path-driven causes

### Over-the-top (out-to-in path)  [confidence: plausible]

**Definition:** Trail elbow moves away from body / out in front of
chest during transition; shoulders open early in downswing; club
approaches ball from outside the target line.

**Primary indicators:**
- `trail_elbow_position_at_P4_to_P7` (positive = moves outward
  instead of dropping toward trail hip)
- `shoulder_rotation_proxy_at_P7` (shoulders open at impact —
  values less negative than typical, or positive)

**Appears in:**
- Slice (cause 2) — paired with open face produces curving slice
- Pull (cause 1) — paired with square face produces straight pull
- Shank (cause 3) — paired with hands traveling outward produces
  hosel-first impact

**Consistency check:** Same body indicators across all three. The
differentiator is what the face is doing (open vs square) or what
the hands are doing (traveling outward). Be precise in each KB
entry about which secondary indicators differentiate this symptom
from the others sharing the cause.

---

### Stuck (excessive in-to-out path)  [confidence: plausible]

**Definition:** Trail elbow drops too far behind body; hips
over-rotate while arms lag.

**Primary indicators:**
- `trail_elbow_position_at_P4_to_P7` (negative = drops behind body)
- `hip_rotation_proxy_at_P7` (over-rotated open — value shifted
  further from P4 baseline than typical)

**Appears in:**
- Hook (cause 2) — paired with hand flip produces curving hook
- Push (cause 1) — paired with held neutral face produces straight push

**Consistency check:** Body indicators identical between hook and
push KBs. Differentiator is `trail_wrist_angle_at_P7` — flexed for
hook, neutral for push.

---

### Closed shoulders at top with steep return  [confidence: plausible]

**Definition:** Shoulders under-rotated at top; downswing path is
steep and over-the-top in compensation.

**Primary indicator:**
- `shoulder_rotation_proxy_at_P4` (less negative than typical =
  under-rotated)

**Appears in:**
- Pull (cause 5) — flagged as possibly redundant with over-the-top

**Consistency check:** Weakest cause in the catalog. Revisit in
Phase 3; likely candidate for merging with pull cause 1 or dropping.

---

## Wrist/face-driven causes

### Cupped lead wrist at top (open face at P4)  [confidence: validated]

**Definition:** Lead wrist extended/cupped beyond neutral at top of
backswing; persists into impact.

**Primary indicators (v1 uses trail-side as primary):**
- `trail_wrist_angle_at_P4` (extended past neutral)
- `trail_wrist_angle_at_P7` (still extended at impact)

**Corroborating indicators:**
- `lead_wrist_angle_at_P4` (cupped past threshold — low weight due
  to lead-side visibility)
- `lead_wrist_angle_at_P7` (still cupped — additionally motion-noisy)

**Appears in:**
- Slice (cause 1) — highest-confidence slice indicator

**Consistency check:** Validated on swing_16 fault demo (~52°
trail-wrist separation at P4 between cupped and bowed demos).
Coaching language remains in lead-wrist terms.

---

### Bowed lead wrist at top (closed face at P4)  [confidence: validated]

**Definition:** Lead wrist flexed/bowed beyond neutral at top.

**Primary indicators:**
- `trail_wrist_angle_at_P4` (flexed past neutral)
- `trail_wrist_angle_at_P7` (still flexed at impact)

**Corroborating indicators:**
- `lead_wrist_angle_at_P4`, `lead_wrist_angle_at_P7` (low weight)

**Appears in:**
- Hook (cause 1) — mirror of slice cause 1

**Consistency check:** Validated on swing_17 fault demo. Uses the
same trail-wrist feature as slice cause 1 with opposite sign.

---

### Scooping / flipping at impact (cupped wrist at P7)  [confidence: plausible]

**Definition:** Hands flip upward through impact, adding loft and
raising low point.

**Primary indicators:**
- `trail_wrist_angle_at_P7` (extended at impact — the scoop pattern)
- `head_vertical_change_P1_to_P7` (often paired with weight
  staying back)

**Appears in:**
- Thin contact (cause 4)

**Consistency check:** Shares the P7 wrist indicator with slice's
cause 1, but the diagnostic context is different (slice = face open
producing curve; thin = scoop producing high low-point). The KB
matcher handles this correctly because scoring is per-symptom.
P7 wrist measurement is motion-jitter noisy at 60fps — expect this
cause to be less reliable than the P4-based wrist causes.

---

### Body stall with hand flip through impact  [confidence: plausible]

**Definition:** Hip rotation slows or stops between impact and
finish; hands take over and flip face closed.

**Primary indicators:**
- `hip_rotation_change_P7_to_P10` (small or negative = rotation
  slowed)
- `lead_arm_angle_at_P7` (lead arm collapsing)

**Appears in:**
- Hook (cause 4)

**Consistency check:** Worth noting that cause 5 below (trail hand
overactive) is the "downstream" version of this — body stall is
the root, trail hand flip is the consequence. Phase 3 may reveal
whether to keep both or merge.

---

### Trail hand overactive at impact  [confidence: weak]

**Definition:** Trail wrist breaks down / over-flexes through
impact, flipping face closed late.

**Primary indicators:**
- `trail_wrist_angle_at_P7` (excessively flexed)
- Paired with `lead_wrist_angle_at_P7` (cupped — the flip signature)

**Appears in:**
- Hook (cause 5)

**Consistency check:** P7 wrist measurement is motion-jitter noisy
at 60fps. This cause is inherently harder to diagnose in v1 than
its P4 counterparts. Expect more frequent hits to the "no clear
cause" fallback. v2 with 120+ fps filming may restore reliability.

---

## Release-timing causes

### Casting / early release  [confidence: plausible]

**Definition:** Wrist angle (hinge between lead arm and club) lost
early in the downswing.

**Primary indicators:**
- `trail_wrist_angle_at_P5_proxy` (extended earlier than typical —
  interpolated between P4 and P7)
- `lead_wrist_angle_at_P5_proxy` (paired, low weight due to lead-side
  visibility)

**Appears in:**
- Fat contact (cause 3) — club reaches full extension behind ball
- Thin contact (cause 3) — paired with pull-up compensation
- Lack of distance (cause 3) — releases stored speed before impact

**Consistency check:** The three KB entries should use identical
P5-proxy features and identical thresholds. The catalog's main
argument for prioritizing real P5 detection in a v1 patch — three
high-priority causes are all measured imprecisely by interpolation.

---

## Sequencing and tempo causes

### Arms-dominant downswing / broken kinetic chain  [confidence: plausible]

**Definition:** Upper body initiates downswing rather than hips;
hips and shoulders rotate together rather than hips leading.

**Primary indicators:**
- `hip_rotation_proxy_at_P4` vs `hip_rotation_proxy_at_P7`
  (hips barely opened between top and impact)
- `shoulder_rotation_proxy_at_P7` (shoulders ahead of or with hips)

**Appears in:**
- Lack of distance (cause 2)

---

### Slow tempo / wrong rhythm  [confidence: validated]

**Definition:** Backswing-to-downswing time ratio off from typical
(~3:1 for irons), or total swing duration unusually long.

**Primary indicators:**
- `tempo_ratio`
- `total_swing_duration`

**Appears in:**
- Lack of distance (cause 4)

**Consistency check:** The only cause in the catalog measured
directly rather than via proxy. Worth giving high confidence_weight
when matched.

---

### Inconsistent tempo  [confidence: plausible]

**Definition:** Tempo varies across swings — sometimes smooth,
sometimes rushed.

**Primary indicators:**
- `tempo_ratio_stddev`
- `total_swing_duration_stddev`

**Appears in:**
- Inconsistent contact (cause 2)

---

## Range-of-motion causes

### Insufficient body rotation / short backswing  [confidence: validated]

**Definition:** Shoulders and/or hips under-rotated at top of
backswing.

**Primary indicators:**
- `shoulder_rotation_proxy_at_P4` (less negative than typical)
- `hip_rotation_proxy_at_P4` (less negative than typical)

**Appears in:**
- Lack of distance (cause 1)

**Consistency check:** Validated on swing_25 fault demo
(hip_rotation_proxy_at_P4 z = +4.44). The
`shoulder_rotation_proxy_at_P4` feature also appears in pull
cause 5 ("closed shoulders at top") — same feature, different
threshold direction.

---

### Collapsed swing radius / bent lead arm  [confidence: plausible]

**Definition:** Lead arm bent at top (shortens radius); lead arm
collapses through impact ("chicken wing").

**Primary indicators:**
- `lead_elbow_angle_at_P4` (smaller = more bent at top)
- `lead_arm_angle_at_P7` (smaller = collapsed through impact)

**Appears in:**
- Lack of distance (cause 6)

**Consistency check:** Threshold needs to be forgiving — slight
lead-arm bend is common and not always a fault.

---

## Connection / arm-position causes

### Arms-disconnect / arms extending away from body in downswing  [confidence: plausible]

**Definition:** Lead arm separates from body during downswing;
hands travel away from body line.

**Primary indicators:**
- `lead_arm_to_torso_angle_at_P5_proxy`
- `hand_distance_from_body_at_P7` (compared to `_at_P1`)

**Appears in:**
- Shank (cause 5)

**Consistency check:** Distinct from over-the-top (torso-driven);
this is arms-only. Phase 3 may need to verify the distinction is
detectable.

---

### Weight on toes / diving into ball  [confidence: weak]

**Definition:** Weight rolls onto toes during downswing; body tips
toward ball.

**Primary indicators:**
- `head_vertical_change_P1_to_P7` (positive = head raised — the
  pose-visible proxy for diving toward ball)
- `ankle_displacement_at_P7` (proxy, noted unreliable due to
  down-the-line ankle occlusion)

**Appears in:**
- Shank (cause 4)

**Consistency check:** Explicitly noted measurement weakness on
the ankle indicator. Likely diagnosed in practice as a partner of
early extension rather than independently.

---

## Setup causes

These are pre-swing positioning issues, not in-swing motion. Tagged
`category: setup` in the KB. All share the property that they
should be framed differently in LLM output ("before changing your
swing, check this") and may benefit from being surfaced first when
present.

### Standing too close to ball  [confidence: plausible]

**Indicators:**
- `hand_distance_from_body_at_P1` (small / well below baseline)

**Appears in:** Shank (cause 2)

**Consistency check:** 19% CV on the normal baseline; needs
conservative thresholds. Expect reliable detection only for
extreme cases in v1.

---

### [DROPPED FROM v1] Aim left (alignment cause of pull) — Pull cause 2

Was to depend on `shoulder_line_at_P1` and `hip_line_at_P1`.
Both features dropped in Phase 2 — from down-the-line view, the
target line is the camera axis, so alignment relative to that line
is not measurable. See `docs/measurement_visibility_decisions.md`.
Restored if v2 adds face-on camera view.

---

### [DROPPED FROM v1] Aim right (alignment cause of push) — Push cause 3

Same as above, mirror direction.

---

### [DROPPED FROM v1] Weak grip — Slice cause 3

Was to depend on `lead_hand_knuckle_visibility_at_P1`. Dropped
without implementation because (1) MediaPipe pose lacks true hand
keypoints, (2) lead-hand visibility from down-the-line is 0.15-0.40,
(3) grip strength rotates around the shaft axis which is the camera
axis at address. See `docs/measurement_visibility_decisions.md`.

---

### [DROPPED FROM v1] Strong grip — Hook cause 3

Same as above.

---

### Ball position too far forward  [DROPPED FROM v1 — deferred to v2]

Would depend on ball detection in-frame, which v1 does not
implement. Deferred to v2 or to user-provided free-text context.

Was to appear in: Pull (cause 3), Thin contact (cause 5)

---

### Ball position too far back  [DROPPED FROM v1 — deferred to v2]

Same as above, mirror direction. Was to appear in: Push (cause 4).

---

## Speed-related causes

### [DROPPED FROM v1] Reverse weight shift / no ground use — Lack-of-distance cause 5

Was to depend on `weight_distribution_proxy_at_P4` and
`weight_distribution_proxy_at_P7`. Both features dropped in Phase 2
(target axis IS camera axis). Lack of distance retains five other
causes in v1; losing this one is survivable. See
`docs/measurement_visibility_decisions.md`.

---

## Variance causes (inconsistent-contact-specific)

These causes are unique to the inconsistent-contact symptom because
they score against feature variance (stddev/range) rather than
feature values.

### Inconsistent setup  [confidence: plausible]

**Indicators:**
- `head_displacement_P1_to_P4_stddev` (variance in P4 head position)
- `hand_distance_from_body_at_P1_stddev`
- `spine_angle_at_P1_stddev`
- `knee_flex_lead_at_P1_stddev`, `knee_flex_trail_at_P1_stddev`

**Note:** Original catalog listed `weight_distribution_proxy_at_P1_stddev`
and various head-position/hip-position stddevs. Weight distribution
is dropped in v1. Setup variance in v1 is measured via the features
above.

---

### Inconsistent weight shift / variable low point  [confidence: plausible]

**Indicators:**
- `head_displacement_P1_to_P7_target_axis_stddev`
- `head_vertical_change_P1_to_P7_stddev`

**Note:** Original listed `weight_distribution_proxy_at_P7_stddev`;
replaced by the two head-based variance indicators above.

---

### Inconsistent wrist position at impact  [confidence: plausible]

**Indicators:**
- `trail_wrist_angle_at_P7_stddev` (primary — visibility)
- `lead_wrist_angle_at_P7_stddev` (corroborating)

---

### Inconsistent top-of-backswing position  [confidence: plausible]

**Indicators:**
- `trail_wrist_angle_at_P4_stddev` (primary)
- `lead_wrist_angle_at_P4_stddev` (corroborating)
- `shoulder_rotation_proxy_at_P4_stddev`
- `spine_angle_at_P4_stddev`

---

(Inconsistent tempo — covered above under sequencing/tempo)

**Consistency check across variance causes:** Every per-swing
feature referenced in any non-inconsistency cause should also be
available as a `_stddev` variant for use here. The features
inventory makes this explicit.

---

## Cross-cutting observations

**Count of distinct causes in v1:** approximately 17 (down from 22
in the pre-Phase-2 catalog after dropping the 5 invisible-axis
causes and deferring the ball-position causes to v2).

**Root causes appearing in 3+ symptoms:**
- Early extension (5 symptoms)
- Over-the-top (3 symptoms)
- Hanging back (3 symptoms)
- Casting (3 symptoms)

These deserve the most careful threshold tuning in Phase 3 —
getting them right benefits multiple symptoms simultaneously.

**Causes flagged for likely merging in Phase 3:**
- Loss of posture (thin cause 2) with early extension
- Closed shoulders at top (pull cause 5) with over-the-top

**Symptom-level cause counts after v1 drops:**
- Slice: 4 causes (was 5; lost weak grip)
- Hook: 4 causes (was 5; lost strong grip)
- Pull: 3 causes (was 5; lost aim-left and ball-position)
- Push: 3 causes (was 5; lost aim-right and ball-position)
- Fat contact: 4 causes (was 4)
- Thin contact: 4 causes (was 5; lost ball-position)
- Lack of distance: 5 causes (was 6; lost no-ground-use)
- Inconsistent contact: 5 causes (was 5)
- Shank: 5 causes (was 5)

Every symptom still has at least 3 causes; no symptom becomes
undiagnosable. Pull and push are the most affected (each lost 2
causes) — the LLM layer's "no clear cause detected" fallback will
fire more frequently for these two symptoms than for the others.