"""
Shoulder and hip rotation proxies at P4, P7, and P10 (hips only).

The measurement problem
-----------------------
True rotation is a 3D quantity measured around the body's vertical
axis. From a single down-the-line 2D camera, that axis is roughly
perpendicular to the image plane and rotation cannot be measured
directly. We use a projection-based proxy: the horizontal (image-x)
signed separation between paired landmarks (lead and trail shoulder,
or lead and trail hip), normalized by a stable body reference length.

    shoulders parallel to target line (address)  ->  small separation
    shoulders perpendicular to target line       ->  large separation

The sign of (trail.x - lead.x) distinguishes backswing rotation from
follow-through rotation.

Normalization: ankle-to-hip vertical distance at P1
---------------------------------------------------
We normalize by the vertical distance from the mid-ankle to the mid-hip
at P1. This is:

    - A vertical body dimension, so it's cleanly projected from a
      down-the-line camera (not measured along the camera axis)
    - Rotation-independent (feet don't rotate; hips barely move at address)
    - Stable across sessions for the same golfer (torso length is fixed)
    - Empirically the lowest-CV reference in the candidate set (~7% CV
      across 15 normal swings, vs. 30%+ for horizontal separations)

An earlier design used horizontal shoulder-separation-at-P1 as the
reference. That produced catastrophic sensitivity to the P1 baseline:
swings where the shoulders happened to address more parallel to the
camera had huge normalization ratios because the denominator was tiny.
An intermediate design tried ankle-to-ankle horizontal distance, which
worked in principle but has the same "measuring a horizontal quantity
along the camera line of sight" problem in miniature.

The vertical reference is stable because torso length is a real body
dimension, not a projection artifact.

Sign convention for the output
------------------------------
For a right-handed golfer in a proper down-the-line setup:
    negative  -> rotated in the backswing direction (typical at P4)
    ~0        -> shoulders/hips roughly parallel to target line
    positive  -> rotated in the follow-through direction (typical at P10)

Impact (P7) values in practice sit between fully-rotated-back (P4)
and fully-rotated-through (P10). They do not reliably cross zero into
the positive range at impact for typical amateur swings.

Limitations
-----------
- Spine tilt contaminates the projection. If the player tilts their
  spine sideways while rotating, the shoulder line tilts with it and
  the projected x-separation changes for reasons that aren't rotation.
- The proxy is unitless (fraction of ankle-to-hip vertical). KB
  thresholds tuned in Phase 3.
- If the reference length can't be measured at P1 (occluded ankles
  or hips), all rotation features return NaN.
"""

from __future__ import annotations

import numpy as np

from ..landmarks import Handedness, lead, trail
from ..primitives import is_valid, midpoint


# Minimum reference length (in normalized image coordinates 0-1) for
# a valid rotation baseline. Real ankle-to-hip vertical distances in
# a properly-framed swing sit around 0.15-0.20 in normalized units;
# anything below 0.05 suggests the pose is degenerate or the framing
# has cropped major body regions.
_MIN_REFERENCE_LENGTH = 0.05


class RotationExtractor:
    """Shoulder- and hip-rotation proxies at swing checkpoints."""

    FEATURES = (
        "shoulder_rotation_proxy_at_P4",
        "shoulder_rotation_proxy_at_P7",
        "hip_rotation_proxy_at_P4",
        "hip_rotation_proxy_at_P7",
        "hip_rotation_proxy_at_P10",
        "hip_rotation_change_P7_to_P10",
    )

    def extract(
        self,
        pose_landmarks: np.ndarray,
        checkpoints: dict[str, int],
        handedness: Handedness = Handedness.RIGHT_HANDED,
    ) -> dict[str, float]:
        out: dict[str, float] = {}

        # Establish the P1 body-reference length.
        reference_length = self._body_reference_length(
            pose_landmarks, checkpoints["P1"], handedness,
        )

        # Shoulders: P4, P7.
        for cp_name in ("P4", "P7"):
            frame = checkpoints[cp_name]
            out[f"shoulder_rotation_proxy_at_{cp_name}"] = self._compute_proxy(
                pose_landmarks, frame, "shoulder", handedness, reference_length,
            )

        # Hips: P4, P7, P10.
        for cp_name in ("P4", "P7", "P10"):
            frame = checkpoints[cp_name]
            out[f"hip_rotation_proxy_at_{cp_name}"] = self._compute_proxy(
                pose_landmarks, frame, "hip", handedness, reference_length,
            )

        # Delta: rotation from impact to finish. Small or negative
        # indicates body stall through impact (hook cause 4). NaN
        # propagates cleanly through subtraction if either operand
        # is NaN.
        out["hip_rotation_change_P7_to_P10"] = (
            out["hip_rotation_proxy_at_P10"] - out["hip_rotation_proxy_at_P7"]
        )

        return out

    @staticmethod
    def _body_reference_length(
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
    ) -> float:
        """
        Vertical distance from mid-ankle to mid-hip at the given frame.

        Uses midpoints of the paired landmarks so the reference is
        robust to which foot or hip is more visible.
        """
        lead_ankle = pose_landmarks[frame, lead("ankle", handedness)]
        trail_ankle = pose_landmarks[frame, trail("ankle", handedness)]
        lead_hip = pose_landmarks[frame, lead("hip", handedness)]
        trail_hip = pose_landmarks[frame, trail("hip", handedness)]
        if not is_valid(lead_ankle, trail_ankle, lead_hip, trail_hip):
            return float("nan")

        ankle_mid = midpoint(lead_ankle, trail_ankle)
        hip_mid = midpoint(lead_hip, trail_hip)
        return float(abs(ankle_mid[1] - hip_mid[1]))

    @staticmethod
    def _signed_separation(
        pose_landmarks: np.ndarray,
        frame: int,
        joint: str,
        handedness: Handedness,
    ) -> float:
        """Signed image-x separation (trail.x - lead.x) at the given frame."""
        lead_lm = pose_landmarks[frame, lead(joint, handedness)]
        trail_lm = pose_landmarks[frame, trail(joint, handedness)]
        if not is_valid(lead_lm, trail_lm):
            return float("nan")
        return float(trail_lm[0] - lead_lm[0])

    @classmethod
    def _compute_proxy(
        cls,
        pose_landmarks: np.ndarray,
        frame: int,
        joint: str,
        handedness: Handedness,
        reference_length: float,
    ) -> float:
        """Signed separation at frame / reference length baseline."""
        if not np.isfinite(reference_length) or reference_length < _MIN_REFERENCE_LENGTH:
            return float("nan")
        sep = cls._signed_separation(pose_landmarks, frame, joint, handedness)
        if not np.isfinite(sep):
            return float("nan")
        return sep / reference_length