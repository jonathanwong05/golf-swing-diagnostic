# Measurement visibility decisions

This document captures the two structural rules Phase 2 established
about what can and cannot be measured from down-the-line 2D pose,
and why each rule exists. Both rules govern feature-design decisions
throughout the project.

The rules are:

1. **Measurement vs. communication decoupling.** Where a feature
   can be measured on either side of the body, use the side the
   camera sees clearly; translate to conventional coaching language
   in user-facing output.

2. **The invisible axis principle.** If a measurement's signal
   lives along or rotates around the camera's line of sight, the
   camera cannot see it. Do not build a feature that pretends to
   measure it. Drop the feature and document why.

Both rules apply to any future features considered for v1 or v2.

---

# Rule 1: Measurement vs. communication

## The rule

Where a feature can be measured on either side of the body (lead or
trail), the system uses whichever side is more reliably visible from
the camera angle in use as the primary measurement, and communicates
findings to the user in the conventional coaching frame (typically
lead-side language). The measurement substrate and the communication
substrate are decoupled by design.

## Why this exists

The v1 system uses down-the-line video. Lead-side body landmarks
(left side for a right-handed golfer) are on the far side of the
body from the camera and are frequently occluded — MediaPipe
visibility scores for the lead wrist, lead elbow, and lead-side hand
landmarks routinely drop to 0.1-0.6 across the swing. Trail-side
landmarks see visibility scores of 0.85-0.97 over the same frames.

Trying to measure a feature primarily from low-visibility landmarks
produces noisy or misleading values, even when the geometric
computation itself is correct. The measurement isn't wrong; the
inputs are.

At the same time, coaching language is dominated by lead-side cues
for almost every wrist, arm, and shoulder fault. "Bow your lead
wrist at the top" is a standard coaching feel; "extend your trail
wrist less" is not. Users will recognize lead-side cues from
YouTube, coaches, and golf media; trail-side cues will read as
foreign.

The resolution: measure from whichever side the camera sees clearly;
translate to lead-side language in the user-facing output.

## How it applies in practice

For each affected feature, both lead-side and trail-side versions
are computed and stored in `SwingFeatures`. The KB matcher uses the
higher-visibility side as the primary indicator with full confidence
weight, and the lower-visibility side as a secondary indicator with
reduced confidence weight. The feel cues, fix instructions, and
LLM-generated explanations are written in lead-side coaching
language regardless of which side was used for measurement.

For down-the-line v1, this means:

- **Wrist features:** trail-wrist is primary; lead-wrist is
  secondary. Applies to P1, P4, P5_proxy, and P7.
- **Arm path / "over the top":** trail-elbow is primary
  (`trail_elbow_position_at_P4_to_P7`); lead-side arm path
  measurements are not used in v1.
- **Other lead-side features** (lead elbow angle at P4, lead arm
  angle at P7): kept in the schema for completeness, flagged in the
  noisy-features list, used as corroborating indicators only with
  low confidence weight.

If face-on or other camera angles are added in v2, this rule applies
again with the visibility map updated for the new view. Lead-side
features that are well-visible from face-on become the primary
measurement for that angle.

## What this is not

This is not a workaround or a temporary fix. It is the structural
response to the inherent visibility limits of 2D pose estimation
from a fixed camera angle. Future iterations may add additional
camera angles (which would supply additional measurements), but the
decoupling between measurement and communication remains correct
regardless.

## Evidence that drove this decision

Empirical inspection during Phase 2, on swings 9 and 15 from the
normal-swing dataset: