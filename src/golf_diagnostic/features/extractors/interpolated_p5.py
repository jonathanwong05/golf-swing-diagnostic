"""
Interpolated P5 (early downswing) features.

P5 is the midpoint between the top of the backswing (P4) and impact
(P7), roughly when the lead arm is parallel to the ground. It
matters diagnostically because it's where the swing decides whether
to cast (release wrist hinge early) or hold lag. Three v1 causes
depend on P5 measurements (casting in fat/thin/distance), plus one
shank cause (arms disconnect).

P5 is not directly detected in v1. This extractor approximates it
by picking the frame halfway (in frame count) between P4 and P7 and
measuring features at that frame from raw landmarks. This is not
the same as "lead arm parallel to ground" — the frame midpoint sits
earlier in the downswing than true P5 because the downswing
accelerates through impact — but it's a stable proxy that carries
the discriminating signal we need for casting detection.

Design choice: measure at an interpolated frame, not interpolate
between feature values
--------------------------------------------------------------------
Alternative rejected: compute the P4 and P7 values and take their
arithmetic mean. This dilutes the casting signal because the P7
wrist value is (correctly) neutral for both casters and non-casters
— averaging it in pulls a caster's early-release signal back toward
"normal" and shrinks the discriminating separation. Measuring at the
midpoint frame directly preserves the mid-downswing wrist position
for whoever the swing produces.

Features
--------
lead_wrist_angle_at_P5_proxy:
    Signed wrist angle at the interpolated frame. Same convention as
    the wrist extractor: positive = cupped, negative = bowed.

trail_wrist_angle_at_P5_proxy:
    Same, trail side.

lead_arm_to_torso_angle_at_P5_proxy:
    Interior angle at the lead shoulder, formed by
    lead_elbow -> lead_shoulder -> mid_hip. Small = arm tucked
    against torso (connected). Large = arm has separated. Shank
    cause 5 uses this.

hand_path_proxy_at_P5_proxy:
    Delta of hand-to-body distance from P4 to interpolated P5.
    Positive = hands moved outward (away from body); negative =
    hands moved inward. Uses the same perpendicular-distance-to-
    torso-axis measurement as the position extractor's
    hand_distance_from_body features, normalized by ankle-to-hip
    vertical at P1. Shank cause 3 uses this.

Limitations
-----------
- The interpolated frame is not true P5 (lead arm parallel).
  Diagnostic power lower than direct P5 detection would give.
  Documented as v1 patch opportunity in docs/spec.md.
- P7 wrist measurement is motion-noisy at 60fps; some of that noise
  bleeds through when computing wrist at the P5 midpoint frame,
  though less than at P7 itself since mid-downswing frames sit in
  a slower part of the swing.
- No casting fault demos exist in the current dataset. Structural
  validation only; diagnostic validation deferred until casting
  demos are filmed.
"""

from __future__ import annotations

import math

import numpy as np

from ..landmarks import Handedness, lead, trail
from ..primitives import (
    angle_at_joint,
    distance,
    is_valid,
    midpoint,
    signed_angle_2d,
)


# Minimum ankle-to-hip vertical length (normalized image coords) for
# a valid P1 body-scale reference. Matches position/rotation
# extractors.
_MIN_REFERENCE_LENGTH = 0.05


class InterpolatedP5Extractor:
    """P5-proxy features via frame interpolation between P4 and P7."""

    FEATURES = (
        "lead_wrist_angle_at_P5_proxy",
        "trail_wrist_angle_at_P5_proxy",
        "lead_arm_to_torso_angle_at_P5_proxy",
        "hand_path_proxy_at_P5_proxy",
    )

    def extract(
        self,
        pose_landmarks: np.ndarray,
        checkpoints: dict[str, int],
        handedness: Handedness = Handedness.RIGHT_HANDED,
    ) -> dict[str, float]:
        p1 = checkpoints["P1"]
        p4 = checkpoints["P4"]
        p7 = checkpoints["P7"]

        nan_result = {name: float("nan") for name in self.FEATURES}

        if p7 <= p4:
            return nan_result

        p5 = round((p4 + p7) / 2)

        return {
            "lead_wrist_angle_at_P5_proxy": self._wrist_angle(
                pose_landmarks, p5, handedness, side="lead"
            ),
            "trail_wrist_angle_at_P5_proxy": self._wrist_angle(
                pose_landmarks, p5, handedness, side="trail"
            ),
            "lead_arm_to_torso_angle_at_P5_proxy": self._lead_arm_to_torso(
                pose_landmarks, p5, handedness
            ),
            "hand_path_proxy_at_P5_proxy": self._hand_path_delta(
                pose_landmarks, p1, p4, p5, handedness
            ),
        }

    # ------------------------------------------------------------------
    # Wrist angle at a frame (matches wrist extractor's sign convention)
    # ------------------------------------------------------------------

    @staticmethod
    def _wrist_angle(
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
        side: str,
    ) -> float:
        """
        Signed wrist angle: forearm-to-hand vector angle.
        Positive = cupped (extended), negative = bowed (flexed).
        Matches WristExtractor's convention.
        """
        resolver = lead if side == "lead" else trail
        elbow = pose_landmarks[frame, resolver("elbow", handedness)]
        wrist = pose_landmarks[frame, resolver("wrist", handedness)]
        hand = pose_landmarks[frame, resolver("index", handedness)]
        if not is_valid(elbow, wrist, hand):
            return float("nan")

        forearm_vec = wrist[:2] - elbow[:2]
        hand_vec = hand[:2] - wrist[:2]
        angle = signed_angle_2d(forearm_vec, hand_vec)
        if not math.isfinite(angle):
            return float("nan")
        return float(angle)

    # ------------------------------------------------------------------
    # Lead arm to torso: interior angle at lead shoulder,
    # lead_elbow -> lead_shoulder -> mid_hip
    # ------------------------------------------------------------------

    @staticmethod
    def _lead_arm_to_torso(
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
    ) -> float:
        lead_shoulder = pose_landmarks[frame, lead("shoulder", handedness)]
        lead_elbow = pose_landmarks[frame, lead("elbow", handedness)]
        lead_hip = pose_landmarks[frame, lead("hip", handedness)]
        trail_hip = pose_landmarks[frame, trail("hip", handedness)]
        if not is_valid(lead_shoulder, lead_elbow, lead_hip, trail_hip):
            return float("nan")

        mid_hip = midpoint(lead_hip, trail_hip)
        angle = angle_at_joint(lead_elbow, lead_shoulder, mid_hip)
        if not math.isfinite(angle):
            return float("nan")
        return float(angle)

    # ------------------------------------------------------------------
    # Hand path proxy: hand-distance-from-body delta, P4 -> P5.
    # ------------------------------------------------------------------

    @classmethod
    def _hand_path_delta(
        cls,
        pose_landmarks: np.ndarray,
        p1: int,
        p4: int,
        p5: int,
        handedness: Handedness,
    ) -> float:
        reference_length = cls._body_reference_length(pose_landmarks, p1, handedness)
        if not math.isfinite(reference_length) or reference_length < _MIN_REFERENCE_LENGTH:
            return float("nan")

        dist_p4 = cls._hand_distance_from_body(pose_landmarks, p4, handedness)
        dist_p5 = cls._hand_distance_from_body(pose_landmarks, p5, handedness)
        if not (math.isfinite(dist_p4) and math.isfinite(dist_p5)):
            return float("nan")

        return float((dist_p5 - dist_p4) / reference_length)

    @staticmethod
    def _hand_distance_from_body(
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
    ) -> float:
        """
        Perpendicular distance from hand midpoint to torso axis
        (mid_shoulder -> mid_hip line). Unnormalized; caller divides
        by body reference length.
        """
        lead_shoulder = pose_landmarks[frame, lead("shoulder", handedness)]
        trail_shoulder = pose_landmarks[frame, trail("shoulder", handedness)]
        lead_hip = pose_landmarks[frame, lead("hip", handedness)]
        trail_hip = pose_landmarks[frame, trail("hip", handedness)]
        lead_wrist = pose_landmarks[frame, lead("wrist", handedness)]
        trail_wrist = pose_landmarks[frame, trail("wrist", handedness)]
        if not is_valid(
            lead_shoulder, trail_shoulder, lead_hip, trail_hip,
            lead_wrist, trail_wrist,
        ):
            return float("nan")

        mid_shoulder = midpoint(lead_shoulder, trail_shoulder)
        mid_hip = midpoint(lead_hip, trail_hip)
        hand_mid = midpoint(lead_wrist, trail_wrist)

        # Perpendicular distance from hand_mid to line through
        # mid_shoulder and mid_hip. |cross(torso_vec, hand_offset)| / |torso_vec|.
        torso_vec = mid_hip - mid_shoulder
        hand_offset = hand_mid - mid_shoulder
        torso_len = float(np.linalg.norm(torso_vec))
        if torso_len < 1e-9:
            return float("nan")
        cross_z = torso_vec[0] * hand_offset[1] - torso_vec[1] * hand_offset[0]
        return abs(cross_z) / torso_len

    # ------------------------------------------------------------------
    # Body-scale reference: ankle-to-hip vertical at P1.
    # (Duplicated from rotation/position extractors per the
    # "extractors don't import from each other" rule.)
    # ------------------------------------------------------------------

    @staticmethod
    def _body_reference_length(
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
    ) -> float:
        lead_ankle = pose_landmarks[frame, lead("ankle", handedness)]
        trail_ankle = pose_landmarks[frame, trail("ankle", handedness)]
        lead_hip = pose_landmarks[frame, lead("hip", handedness)]
        trail_hip = pose_landmarks[frame, trail("hip", handedness)]
        if not is_valid(lead_ankle, trail_ankle, lead_hip, trail_hip):
            return float("nan")

        ankle_mid = midpoint(lead_ankle, trail_ankle)
        hip_mid = midpoint(lead_hip, trail_hip)
        return float(abs(ankle_mid[1] - hip_mid[1]))