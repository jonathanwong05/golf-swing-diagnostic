# v2 Priorities

Features and changes deferred from v1, ranked by impact on system
accuracy and user-visible quality. This document is the answer to
"if we had another 3-6 months to work on this, what would we do
next?"

Written at the end of Phase 4, after end-to-end pipeline testing
made several v1 limitations concrete in a way earlier phases could
only anticipate.

---

## 1. Face-on camera view (highest impact)

**What it unlocks:** every feature dropped from v1 under the
"invisible axis" principle (see
`docs/measurement_visibility_decisions.md`) becomes measurable from
face-on view. The camera axis is no longer the target axis;
lateral displacements, alignment relative to the target line, and
weight distribution all fall in the visible plane.

**Restored features:**
- `weight_distribution_proxy_at_{P1, P4, P7}` (3 fields)
- `shoulder_line_at_P1`, `hip_line_at_P1` (setup alignment)
- `lead_hand_knuckle_visibility_at_P1` (grip strength proxy)
- Full-confidence lead-side wrist features (the far side of the
  body down-the-line becomes the near side face-on)

**Restored KB causes:**
- slice cause 3 (weak grip)
- hook cause 3 (strong grip)
- pull cause 2 (aim left)
- push cause 3 (aim right)
- lack_of_distance cause 5 (no ground use)

**Causes returned to proper primary indicator (currently on weak
fallbacks in v1):**
- reverse pivot: back to `weight_distribution_proxy_at_P4`
- hanging back: back to `weight_distribution_proxy_at_P7`
  (currently uses `head_displacement_P1_to_P7_target_axis` as a
  validated but weaker proxy)
- early extension: gains the hip-thrust signal explicitly
  (currently reads via `spine_angle_change_P1_to_P7` alone)

**Why this is priority 1:**

The dropped causes aren't tail-risk. Weak grip is one of the top
three amateur slice causes. Alignment errors are among the most
common pull/push causes. Aim errors are extremely common. During
Phase 4 testing (`test_pipeline.py` Case B), the fallback message
we produced explicitly told the user that grip and alignment are
"invisible from this angle" — the tool is honest about its
limitations, but that honesty exposes how much the limitations are
costing.

Pull and push symptoms each lost 2 causes to v1 constraints and
have only 2-3 remaining causes each. They will hit the "no clear
cause" fallback more frequently than the other symptoms — this is
knowable in advance, not a Phase 5 discovery.

**What building this requires:**

1. A face-on pose extractor. MediaPipe itself is angle-agnostic;
   the extractor code changes are in the geometric primitives —
   what "target axis" means, which landmarks project cleanly,
   which normalization dimension is stable. From face-on, ankle-
   to-ankle horizontal separation is stable (as opposed to
   ankle-to-hip vertical, which is what v1 uses). The invisible
   axis becomes rotation depth — face-on view can't measure hip
   rotation angle well, which was easy down-the-line.
2. Face-on segmentation. P1/P4/P7/P10 detection uses wrist height
   and velocity — the height detection still works face-on. Some
   confidence tuning needed but the algorithm is the same.
3. Face-on KB extension. New feature names, new baseline. The
   KB architecture already supports multiple indicators per cause;
   face-on features become additional indicators alongside the
   down-the-line ones.
4. Multi-angle analysis. When a user uploads both angles, the
   matcher sees indicators from both. Missing features from either
   angle produce NaN and don't fire, per existing NaN semantics.
   No matcher code change needed.
5. UI capture guidance. Users need clear instructions and visual
   guides for both camera setups. Getting angle wrong invalidates
   the analysis.

**Estimated effort:** 4-6 weeks (parallel to a version of Phase 2
for the new angle, plus UI work).

**Why we didn't do this in v1:** the "invisible axis" principle
wasn't stated up front. It emerged empirically during Phase 2 as
we hit failures on weight distribution, setup alignment, and grip.
Each drop was treated as an isolated feature failure rather than as
a signal that the camera choice was constraining us more than
expected. Had we started with multi-angle thinking, these features
would have lived from the beginning. The v1 constraint is
retrospectively worth reconsidering.

---

## 2. 120+ fps filming for P7 wrist measurement

**What it unlocks:** reliable trail_wrist_angle at P7 (impact).

**Currently blocked by:** motion-induced pose-tracking jitter at
60fps. Trail-wrist values jump 30-100° between consecutive frames
around impact across all demo types (see `phase2_notes.md` for
empirical detail). Windowing across ±5 frames does not help.

**Restored causes:**
- hook cause 5 (trail hand overactive at impact)
- thin contact cause 4 (scoop at impact)

Both currently fall to the "no clear cause" fallback more often
than the other causes in their symptom because the P7 wrist
indicators are low-confidence in v1.

**Estimated effort:** 1-2 weeks. Mostly UI/UX (guiding users to
record at higher framerate) and re-validating pose extraction at
120fps+. Extractors themselves should work without change.

**Why this is priority 2:** narrower impact than face-on view
(affects 2 causes, not 5), but a straightforward capability upgrade
with no architectural work.

---

## 3. Real P5 detection (mid-downswing)

**What it unlocks:** direct measurement of wrist angles and hand
position at the mid-downswing checkpoint, instead of the current
frame-midpoint interpolation between P4 and P7.

**Restored quality:**
- Fat contact cause 3 (casting)
- Thin contact cause 3 (casting)
- Lack of distance cause 3 (casting / early release)

All three currently rely on `lead_wrist_angle_at_P5_proxy` and
`trail_wrist_angle_at_P5_proxy` — interpolated features flagged as
weak-confidence in the causes catalog. A validated casting demo
plus real P5 detection would move these from "plausible" to
"validated" confidence.

**Estimated effort:** 2-3 weeks. Rule-based P5 detection is likely
brittle; may need a small 1D CNN or temporal classifier trained on
labeled frames. Comparable to expanding to P2/P3/P5/P6/P8/P9 for
full checkpoint coverage.

**Why this is priority 3:** casting is a real cause, but the
interpolation is functional; the improvement is quality-of-signal,
not new capability.

---

## 4. Ball detection in-frame

**What it unlocks:** ball-position setup causes.

**Restored causes:**
- pull cause 3 (ball position too far forward)
- push cause 4 (ball position too far back)
- thin cause 5 (ball position too far forward, thin variant)

**Estimated effort:** 2-4 weeks. Requires either a lightweight
object detector for the ball or user-supplied context ("I set up
with the ball forward"). The former is cleaner; the latter is a
Phase 5 fallback if detection is unreliable.

**Why this is priority 4:** three causes across two symptoms. The
detection accuracy will matter — a false-positive ball position
diagnosis is annoying, so the confidence threshold needs
calibration.

---

## 5. Longitudinal tracking / user accounts

**What it unlocks:**
- Session-over-session comparison ("your last upload showed X, now
  you're doing Y")
- Learning which feels work for which users
- Trend detection (fault getting better or worse over months)
- Basis for future personalization at the model level

**Estimated effort:** 3-4 weeks. Auth, storage, session UI,
comparison logic, and privacy considerations. Not technically
hard; scope-heavy.

**Why this isn't higher:** it's a product feature, not a diagnostic
capability improvement. v1's stateless design is a deliberate
scoping choice, not an oversight. But once face-on and multi-swing
diagnostics are polished, this is the natural next expansion of
the tool's usefulness.

---

## 6. Club tracking (much later)

**What it unlocks:** direct measurement of clubface angle and swing
path. Every "the wrist is a proxy for clubface" caveat in the KB
disappears; the KB's cause definitions can shift from "wrist
position indicates face angle" to "face angle is X degrees open."

**Estimated effort:** 6-12 weeks. Requires custom vision work —
club shaft detection, face tracking, sub-frame temporal
interpolation. Real research, not just integration.

**Why this is priority 6:** it's the biggest architectural change
in v2 by a large margin. Every other v2 priority adds features to
the existing pipeline; club tracking rewrites the pipeline's
epistemic foundation. Worth it eventually — a diagnostic tool with
real face and path measurement is a categorically different
product — but too expensive to do before the other v2 items land.

---

## Meta-observation: v1's "invisible axis" is a stronger constraint than we credited

Reading the Phase 2 and Phase 3 notes, each dropped feature is
framed as an isolated failure — weight distribution can't be
measured from down-the-line, alignment lines are unstable near a
singularity, grip strength requires face-on or actual hand
keypoints. Each of those framings is correct.

But the pattern is more coherent than the sum of drops suggests.
The camera axis is the target line, and everything a golf swing
does relative to the target line is invisible from that angle. The
list of dropped features isn't accidental; it's the same physical
property showing up in different measurements.

v2's face-on view isn't just "a nice-to-have." It's the
architectural correction to a v1 choice that turned out to be more
limiting than expected. The tool becomes materially more accurate
with it, not just more feature-complete.

For Phase 5's README and user-facing documentation, this is worth
being honest about: v1 is down-the-line only; a nontrivial fraction
of user faults may hit the "no clear cause detected" fallback
because the tool can't see grip, alignment, or weight distribution
from this angle. v2 will add face-on capture and target those five
specific dropped causes.

That framing is honest with users and honest about the roadmap. It
also makes the argument for v2 straightforward when the time comes.