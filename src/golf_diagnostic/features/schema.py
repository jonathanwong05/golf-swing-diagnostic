"""
Schema for per-swing and cross-swing feature outputs.

This module is the contract between Phase 2 (feature extraction) and
Phase 4 (KB matching). Every feature name referenced by the KB is
defined here as a typed field on SwingFeatures. The aggregator turns
a list of SwingFeatures into an AggregatedFeatures with mean/stddev/
range for each feature.

Conventions
-----------
- Angles in degrees.
- Signed values where direction matters: cupped > 0, bowed < 0 for
  wrists; toward lead side > 0 for displacements; under-rotated < 0,
  over-rotated > 0 for rotation proxies relative to a neutral pose.
  Per-field sign conventions are documented in the field docstring.
- NaN means "feature unavailable" — either the underlying landmarks
  were missing, the geometry was degenerate, or a required input
  (e.g., ball position) wasn't detected. The KB matcher must treat
  NaN distinctly from a present value: an unavailable feature should
  not match an indicator, but also should not actively contradict one.
- Distances are in normalized image-coordinate units (the same space
  MediaPipe outputs), except where explicitly normalized to a body
  reference like ankle-to-hip vertical.

Phase 2 drops
-------------
The following features were removed from v1 because they can't be
measured reliably from down-the-line pose. See
docs/measurement_visibility_decisions.md for the "invisible axis"
principle that governs these drops.

- weight_distribution_proxy_at_{P1, P4, P7}
- shoulder_line_at_P1, hip_line_at_P1
- lead_hand_knuckle_visibility_at_P1

Field count: 36.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, fields
from typing import Literal

# Feature names referenced by the KB. These strings are the contract.
# Add a new feature: add a field below and add its name here.
# The aggregator iterates over this list rather than dataclass fields
# directly, so internal/derived fields can live on SwingFeatures
# without being aggregated.

FEATURE_NAMES: tuple[str, ...] = (
    # ---------- P1 (address) ----------
    "lead_wrist_angle_at_P1",
    "trail_wrist_angle_at_P1",
    "spine_angle_at_P1",
    "knee_flex_lead_at_P1",
    "knee_flex_trail_at_P1",
    "hand_distance_from_body_at_P1",
    "stance_width_at_P1",

    # ---------- P4 (top of backswing) ----------
    "lead_wrist_angle_at_P4",
    "trail_wrist_angle_at_P4",
    "shoulder_rotation_proxy_at_P4",
    "hip_rotation_proxy_at_P4",
    "spine_angle_at_P4",
    "lead_elbow_angle_at_P4",

    # ---------- P5 (interpolated; v1 proxy) ----------
    "lead_wrist_angle_at_P5_proxy",
    "trail_wrist_angle_at_P5_proxy",
    "lead_arm_to_torso_angle_at_P5_proxy",
    "hand_path_proxy_at_P5_proxy",

    # ---------- P7 (impact) ----------
    "lead_wrist_angle_at_P7",
    "trail_wrist_angle_at_P7",
    "shoulder_rotation_proxy_at_P7",
    "hip_rotation_proxy_at_P7",
    "spine_angle_at_P7",
    "lead_arm_angle_at_P7",
    "hand_distance_from_body_at_P7",
    "ankle_displacement_at_P7",

    # ---------- P10 (finish) ----------
    "hip_rotation_proxy_at_P10",

    # ---------- Deltas (checkpoint-to-checkpoint) ----------
    "head_displacement_P1_to_P4",
    "head_displacement_P1_to_P7_target_axis",
    "head_vertical_change_P1_to_P7",
    "hip_displacement_P1_to_P7_target_axis",
    "hip_vertical_change_P1_to_P7",
    "hip_rotation_change_P7_to_P10",
    "spine_angle_change_P1_to_P4",
    "spine_angle_change_P1_to_P7",

    # ---------- Whole-swing ----------
    "tempo_ratio",
    "total_swing_duration",
)


@dataclass
class SwingFeatures:
    """
    Features computed for a single swing.

    Every field is a single float (or NaN if unavailable). Field names
    match the KB's indicator vocabulary exactly.
    """

    # ---------- P1 (address) ----------
    lead_wrist_angle_at_P1: float
    """Signed cup/bow of lead wrist at address. Positive = cupped, negative = bowed."""

    trail_wrist_angle_at_P1: float
    """Signed cup/bow of trail wrist at address."""

    spine_angle_at_P1: float
    """Forward spine tilt from vertical, degrees. Positive = bent forward toward ball."""

    knee_flex_lead_at_P1: float
    """Interior angle at the lead knee, degrees. 180 = straight, smaller = more flexed."""

    knee_flex_trail_at_P1: float
    """Interior angle at the trail knee."""

    hand_distance_from_body_at_P1: float
    """Perpendicular distance from hand midpoint to torso axis (shoulder-hip line)
    at address, normalized by ankle-to-hip vertical distance at P1.
    Used to flag "standing too close to the ball." Feature has ~19% CV on the
    normal-swing baseline; needs conservative KB thresholds."""

    stance_width_at_P1: float
    """Distance between feet at address, normalized by ankle-to-hip vertical.
    Retained in the schema for reference and possible v2 use; no v1 cause
    currently uses it as a primary indicator."""

    # ---------- P4 (top of backswing) ----------
    lead_wrist_angle_at_P4: float
    """Signed cup/bow of lead wrist at top. Highest-priority slice/hook indicator."""

    trail_wrist_angle_at_P4: float
    """Signed cup/bow of trail wrist at top. Primary measurement in v1
    (trail-side is more visible from down-the-line view; ~52° cupped-vs-bowed
    separation validated on fault demos)."""

    shoulder_rotation_proxy_at_P4: float
    """Shoulder rotation proxy at the top of the backswing.
    Unitless ratio: signed image-x separation of shoulder landmarks
    (trail - lead) normalized by ankle-to-hip vertical distance at P1.
    Sign convention: negative = rotated in backswing direction (typical),
    values closer to zero indicate under-rotation. Normal-swing baseline
    around -0.70 (empirically; Phase 3 tunes thresholds). Not a rotation
    angle in degrees; see docs/phase2_notes.md for design rationale."""

    hip_rotation_proxy_at_P4: float
    """Hip rotation proxy at the top of the backswing.
    Unitless ratio: signed image-x separation of hip landmarks
    (trail - lead) normalized by ankle-to-hip vertical distance at P1.
    Sign convention: negative = rotated in backswing direction (typical),
    values closer to zero indicate under-rotation. Normal-swing baseline
    around -0.40 (empirically). Not a rotation angle in degrees; see
    docs/phase2_notes.md."""

    spine_angle_at_P4: float
    """Spine tilt at top (compare to P1 to detect loss of posture)."""

    lead_elbow_angle_at_P4: float
    """Lead elbow interior angle at top. 180 = straight, smaller = bent (collapsed radius)."""

    # ---------- P5 (interpolated; v1 proxy) ----------
    lead_wrist_angle_at_P5_proxy: float
    """Interpolated between P4 and P7 in v1. Used by casting-related causes."""

    trail_wrist_angle_at_P5_proxy: float
    """Interpolated; pairs with lead at P5 for casting detection."""

    lead_arm_to_torso_angle_at_P5_proxy: float
    """Angle between lead arm and torso in early downswing. Connection indicator for shank."""

    hand_path_proxy_at_P5_proxy: float
    """Direction of hand movement P4 -> interpolated P5.
    Operationalized as the change in hand-to-body distance, P4 -> P5.
    Positive = hands moved outward (away from body), negative = inward."""

    # ---------- P7 (impact) ----------
    lead_wrist_angle_at_P7: float
    """Signed cup/bow at impact. Motion-jitter noisy at 60fps; KB downweights."""

    trail_wrist_angle_at_P7: float
    """Signed cup/bow of trail wrist at impact. Also motion-jitter noisy at 60fps.
    v2 may recommend 120+ fps filming to restore reliability."""

    shoulder_rotation_proxy_at_P7: float
    """Shoulder rotation proxy at impact.
    Same construction as shoulder_rotation_proxy_at_P4. Sign convention:
    values less negative (closer to zero) than at P4 indicate rotation
    back toward address; positive values indicate rotation past address
    toward follow-through. Impact values in practice sit between P4
    (fully back) and P10 (fully through) rather than crossing zero;
    normal-swing baseline around -0.26. See docs/phase2_notes.md."""

    hip_rotation_proxy_at_P7: float
    """Hip rotation proxy at impact.
    Same construction as hip_rotation_proxy_at_P4. Sign convention:
    values less negative than at P4 indicate rotation back toward
    address; positive values indicate rotation past address toward
    follow-through. Normal-swing baseline around -0.18. See
    docs/phase2_notes.md."""

    spine_angle_at_P7: float
    """Spine tilt at impact (compare to P1 for posture/early-extension signal)."""

    lead_arm_angle_at_P7: float
    """Lead arm interior angle at impact. Smaller = chicken-winged."""

    hand_distance_from_body_at_P7: float
    """Hand-to-body distance at impact. Compare to P1 for arm extension."""

    ankle_displacement_at_P7: float
    """Ankle position change from P1 (toes/heels rocking forward).
    Flagged as unreliable from down-the-line; low-confidence indicator."""

    # ---------- P10 (finish) ----------
    hip_rotation_proxy_at_P10: float
    """Hip rotation proxy at the finish position.
    Same construction as hip_rotation_proxy_at_P4. Sign convention:
    positive values indicate rotation in the follow-through direction
    (past address toward the target). Normal-swing baseline around
    +0.44 across the dataset. Used primarily via the P7->P10 delta
    (see hip_rotation_change_P7_to_P10) rather than as a standalone
    indicator. See docs/phase2_notes.md."""

    # ---------- Deltas ----------
    head_displacement_P1_to_P4: float
    """Head movement from address to top, projected onto the target axis
    (trail-ankle -> lead-ankle unit vector at P1).
    Positive = head moved toward target (reverse pivot direction).
    Weak indicator: fires only for extreme reverse pivots. See causes_catalog.md."""

    head_displacement_P1_to_P7_target_axis: float
    """Head movement from address to impact, projected onto the target axis.
    Positive = head moved toward target.
    Negative = head moved away from target (hanging back).
    Validated fault-demo signal — primary hanging-back indicator in v1."""

    head_vertical_change_P1_to_P7: float
    """Head vertical movement from address to impact, in image-y coordinates.
    Positive = head raised (early extension / standing up / diving-into-ball direction).
    Negative = head lowered.
    Note: image-y increases downward in raw pixel space; this field flips the
    sign so that "raised" reads positive to match diagnostic intuition."""

    hip_displacement_P1_to_P7_target_axis: float
    """Hip midpoint movement from address to impact, projected onto the target axis.
    Positive = hips slid toward target (lateral bump/slide).
    Negative = hips slid away from target.
    Note: this is NOT the primary early-extension indicator — early extension is
    hips-toward-camera, which reads as vertical change in image space.
    Currently no v1 cause primarily depends on this; kept for possible v2 use
    (bump-and-hang faults)."""

    hip_vertical_change_P1_to_P7: float
    """Hip midpoint vertical movement from address to impact, in image-y.
    Positive = hips raised.
    Negative = hips lowered.
    Note: CONFOUNDED by natural hip rotation — normal swings already show
    0.05-0.15 units of hip rising from P1 to P7 because rotating hips raise
    the mid-hip point in image space. NOT a clean early-extension indicator
    on its own; use spine_angle_change_P1_to_P7 as primary early-extension
    indicator and treat this as corroborating only. See docs/phase2_notes.md."""

    hip_rotation_change_P7_to_P10: float
    """Change in hip rotation from impact to finish (P10 minus P7).
    Small or negative = body stalled (body-stall hook indicator).
    Computed by the rotation extractor as a delta of the P7 and P10 proxies."""

    spine_angle_change_P1_to_P4: float
    """Change in spine angle from address to top of backswing, in degrees.
    Signed: positive = spine bent more forward at top than at address,
    negative = spine straightened up during backswing (loss of posture).
    Used by thin contact cause 2 (loss of posture)."""

    spine_angle_change_P1_to_P7: float
    """Change in spine angle from address to impact, in degrees.
    Signed: positive = spine bent more forward at impact than at address,
    negative = spine straightened up (early extension direction).
    PRIMARY early-extension indicator in v1 (took over from hip_vertical_change_P1_to_P7
    which is rotation-confounded). Used across slice, push, fat, thin, shank causes."""

    # ---------- Whole-swing ----------
    tempo_ratio: float
    """Backswing duration (P1 -> P4) divided by downswing duration (P4 -> P7).
    Iron neutral target roughly 3.0."""

    total_swing_duration: float
    """Total swing duration P1 -> P10, in seconds."""

    # ----- methods -----

    def to_dict(self) -> dict[str, float]:
        """Return all KB-facing features as a flat name -> value dict."""
        return {name: getattr(self, name) for name in FEATURE_NAMES}

    def get(self, name: str) -> float:
        """Look up a feature by name. Raises KeyError if unknown."""
        if name not in FEATURE_NAMES:
            raise KeyError(f"Unknown feature: {name!r}")
        return getattr(self, name)


# ---------------------------------------------------------------------------
# Aggregated features across multiple swings.
# ---------------------------------------------------------------------------

AggregateKind = Literal["mean", "stddev", "range"]


@dataclass
class AggregatedFeatures:
    """
    Per-feature aggregates across the user's 3-5 uploaded swings.

    Stored as a nested dict {feature_name: {"mean": ..., "stddev": ..., "range": ...}}
    for compactness, but accessed via .get() so consumers don't reach into
    the underlying structure.

    NaN handling: aggregates are computed only over swings where the feature
    is finite. If fewer than two swings have a finite value, stddev and
    range are NaN (no variance estimate possible); mean is NaN if zero
    swings have a finite value.
    """

    n_swings: int
    _values: dict[str, dict[str, float]]

    def get(self, name: str, kind: AggregateKind = "mean") -> float:
        """
        Look up an aggregate for a feature.

        >>> agg.get("lead_wrist_angle_at_P4")             # mean
        >>> agg.get("lead_wrist_angle_at_P4", "stddev")
        """
        if name not in self._values:
            raise KeyError(f"Unknown feature: {name!r}")
        return self._values[name][kind]

    def to_dict(self) -> dict[str, dict[str, float]]:
        """Return the underlying nested dict (read-only by convention)."""
        return self._values


def aggregate(swings: list[SwingFeatures]) -> AggregatedFeatures:
    """
    Compute mean, stddev, and range across a list of per-swing features.

    NaN values are skipped per feature. If fewer than 1 finite value exists
    for a feature, all three aggregates are NaN. If exactly 1, stddev and
    range are NaN but mean is the single value.
    """
    if not swings:
        raise ValueError("Cannot aggregate an empty list of swings.")

    out: dict[str, dict[str, float]] = {}
    for name in FEATURE_NAMES:
        values = [s.get(name) for s in swings]
        finite = [v for v in values if math.isfinite(v)]

        if not finite:
            out[name] = {"mean": math.nan, "stddev": math.nan, "range": math.nan}
            continue

        mean_v = statistics.fmean(finite)

        if len(finite) >= 2:
            stddev_v = statistics.stdev(finite)
            range_v = max(finite) - min(finite)
        else:
            stddev_v = math.nan
            range_v = math.nan

        out[name] = {"mean": mean_v, "stddev": stddev_v, "range": range_v}

    return AggregatedFeatures(n_swings=len(swings), _values=out)