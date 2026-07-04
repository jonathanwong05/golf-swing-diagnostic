# Fault-demo dataset specification

## Purpose

The fault-demo dataset is a set of swings filmed with the deliberate
intent of exaggerating one specific swing **cause** per video. Its
purpose is to validate that each feature in the v1 extractor correctly
responds to the cause it's designed to detect. Without it, every
feature is an untested hypothesis; with it, we can write per-feature
validation tests.

This dataset isolates **causes**, not **symptoms**. The features the
system computes measure causes — cupped wrist, over-the-top path,
early extension, hanging back, etc. Symptoms — slice, hook, pull,
push, fat, thin — are the ball-flight outcomes that arise from
combinations of causes plus face-to-path geometry, and are not
directly demonstrated in this dataset. Validating that each feature
detects its intended cause in isolation is sufficient; we don't need
swings that demonstrate combined cause patterns to validate features
that work independently.

This dataset is separate from the normal-swing dataset (swings 1-15)
and lives alongside it in `data/raw/`. The two datasets serve
different purposes: normal swings test the end-to-end pipeline and
provide a baseline for "what a typical swing looks like"; fault-demo
swings test that the system can distinguish faults from baseline.

## Filming guidelines

Apply the existing `docs/filming_guidelines.md` standards, with these
additions:

- **Frame rate: 60 fps minimum.** Same as the production standard.
- **No ball required.** These are practice swings for testing body
  geometry, not contact-quality measurement. Swing with full
  commitment regardless — a half-hearted no-ball swing is not useful
  data. A piece of tape on the ground to swing at helps maintain
  commitment.
- **Exaggerate the cause.** The goal is high signal-to-noise. A
  subtle version of the cause may not be measurably different from a
  normal swing. Make the cupped wrist clearly cupped; make the
  reverse pivot unmistakably reverse-pivoted.
- **One cause per swing.** Don't combine multiple causes in one
  swing. If a cause you're trying to demonstrate inherently brings
  others along (e.g., reverse pivot tends to cause early extension),
  that's fine — note it in the label — but don't deliberately stack
  unrelated causes.
- **Hold the demonstrated position visibly.** For checkpoint-based
  causes (cupped at top, hanging back at impact), pause briefly at
  the relevant checkpoint if it helps the camera see it. The pause
  doesn't hurt the measurement; the geometry is still correct.
- **Incidental drift is acceptable.** When you exaggerate one cause,
  other features may shift along for the ride (e.g., when demonstrating
  over-the-top, your wrists may incidentally cup). That's fine. The
  validation script checks the *intended* feature for that swing and
  doesn't penalize incidental movement in unrelated features.

## Filming order

Group by cause type to avoid mental fatigue. Film 2-3 takes of each
cause, keep the best one; or keep multiple takes and label them as
duplicates. Duplicates are useful — they give us a stddev across
"the same cause filmed twice" which is itself diagnostic information.

The optional duplicates of wrist causes (#1-4) are recommended
because wrist features are the highest-leverage in the KB and
variance estimation matters most there.

### Wrist causes (highest priority)

These validate the most heavily-referenced features in the KB. Film
these first.

1. **Cupped lead wrist at top.** Feel: back of lead hand pointing
   at the sky at the top of the backswing. Hold the cup through
   impact. Validates: `lead_wrist_angle_at_P4`,
   `trail_wrist_angle_at_P4` (extended), and carry-through to P7.
2. **Bowed lead wrist at top.** Feel: hiding the clubface from the
   sky; lead palm facing the sky. Validates: same features as #1
   with opposite sign.
3. **Scoop / flip at impact.** Feel: trying to lift the ball;
   adding loft with the hands; cupping the wrist through impact.
   Validates: `lead_wrist_angle_at_P7`, `trail_wrist_angle_at_P7`
   (the cup-at-impact pattern, distinct from cup-at-top).
4. **Hold-off / bowed at impact.** Feel: hooding the face through
   impact; bowed lead wrist held through the strike. Validates:
   same features as #3 with opposite sign.

### Path causes

5. **Over-the-top.** Feel: throwing the arms out from the top;
   swinging across the body. Validates:
   `trail_elbow_position_at_P4_to_P7` (out / away from body),
   `shoulder_rotation_proxy_at_P7` (open at impact).
6. **Stuck / inside.** Feel: dropping the trail elbow exaggeratedly
   behind you; club approaching from too far inside. Validates:
   `trail_elbow_position_at_P4_to_P7` (behind body),
   `hip_rotation_proxy_at_P7` (over-rotated).

### Low-point and weight-shift causes

7. **Hanging back.** Feel: weight stays on trail foot through
   impact; head behind ball. Validates:
   `weight_distribution_proxy_at_P7` (trail-side),
   `head_displacement_P1_to_P7` (away from target).
8. **Early extension.** Feel: thrusting hips toward the ball
   during the downswing; standing up through impact. Validates:
   `hip_displacement_P1_to_P7` (toward lead/ball side),
   `spine_angle_at_P7` (more upright than at P1).
9. **Reverse pivot.** Feel: weight moves to lead foot during the
   backswing; head moves toward target at top. Validates:
   `head_displacement_P1_to_P4`,
   `weight_distribution_proxy_at_P4` (lead-side at top).

### Rotation and tempo causes

10. **Short backswing.** Feel: half-swing; insufficient turn.
    Validates: `shoulder_rotation_proxy_at_P4`,
    `hip_rotation_proxy_at_P4` (both small).
11. **Slow / sluggish tempo.** Feel: deliberately slow throughout.
    Validates: `total_swing_duration` (long); `tempo_ratio` may
    stay near baseline if both halves slow proportionally.
12. **Quick / rushed transition.** Feel: short pause at the top,
    fast snap into the downswing. Validates: `tempo_ratio` (low —
    backswing not appreciably longer than downswing).

### Setup causes

13. **Standing too close.** Feel: hands hanging close to the
    thighs at address. Validates: `hand_distance_from_body_at_P1`
    (small).
14. **Ball forward in stance.** Set up with the ball off the lead
    foot. Validates: ball-position-dependent features. May be
    only partially testable in v1 if ball detection isn't yet
    implemented; in that case, validate via relative head and
    foot positions at P1.
15. **Ball back in stance.** Set up with the ball off the trail
    foot. Validates: mirror of #14.

## Total

Fifteen cause demonstrations (swings 16-30). Plus optional duplicates
of the four wrist causes for variance estimation (swings 31-34).
Target: 15-19 demo swings total.

## What's not in this dataset

Two cause patterns from the cause_research document — "over-the-top
with a held square face" (which would produce a pull) and "stuck
in-to-out with a held square face" (which would produce a push) —
are not separately demonstrated here. Each is a combination of two
isolated causes that this dataset already covers:

- Over-the-top path is validated by demo #5.
- Stuck-inside path is validated by demo #6.
- Square-face-at-impact (neutral wrist) is implicitly the absence
  of demos #3 and #4.

If both the path feature and the wrist-at-impact feature work
correctly when validated in isolation, their combined recognition
in real swings is implicitly supported. No additional combined
demos are needed.

## Labeling

As each swing is filmed, add an entry to `data/labels.yaml`. The
label captures the intended cause so the validation script can check
feature outputs against expected patterns. See `data/labels.yaml`
for the format. Each label should:

- Name the intended cause (`intended_fault` field, snake_case)
- List the features expected to respond, with rough magnitude/direction
- Note any incidental movement in other features
- Capture filming notes (the feel used, anything unusual about the take)