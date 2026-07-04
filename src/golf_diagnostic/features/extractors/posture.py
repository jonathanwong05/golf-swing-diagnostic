"""
Posture features: spine angle, knee flex, and lead-arm angles.

All measurements here are interior joint angles or angles relative
to vertical. Cleaner geometry than rotation because they don't
require projecting through a rotation axis — they measure body-
segment angles directly.

Features
--------
- `spine_angle_at_P1/P4/P7`: forward tilt of the spine from vertical,
  in degrees. Computed as the unsigned angle between the mid-hip to
  mid-shoulder vector and the world-vertical direction.
- `knee_flex_{lead,trail}_at_P1`: interior angle at the knee formed
  by hip -> knee -> ankle, in degrees. 180 = straight leg,
  smaller = more flexed.
- `lead_elbow_angle_at_P4`: interior angle at the lead elbow formed
  by shoulder -> elbow -> wrist. 180 = fully extended,
  smaller = collapsed (short swing radius).
- `lead_arm_angle_at_P7`: same formula as lead_elbow_angle_at_P4,
  measured at impact. Small values indicate a "chicken-winged" lead
  arm through the strike.

Visibility caveats
------------------
All lead-side arm features (lead_elbow_angle_at_P4, lead_arm_angle_at_P7)
share the down-the-line lead-side visibility limits documented for
wrist features. Values are computed regardless; downstream confidence
weighting is the KB matcher's responsibility. See
docs/measurement_visibility_decisions.md.

Lead knee at P1 is on the far side of the body from the camera and
will typically have lower visibility than the trail knee.
"""

from __future__ import annotations

import math

import numpy as np

from ..landmarks import Handedness, lead, trail
from ..primitives import angle_at_joint, is_valid, midpoint


class PostureExtractor:
    """Spine, knee, and lead-arm angle features at swing checkpoints."""

    FEATURES = (
        "spine_angle_at_P1",
        "spine_angle_at_P4",
        "spine_angle_at_P7",
        "knee_flex_lead_at_P1",
        "knee_flex_trail_at_P1",
        "lead_elbow_angle_at_P4",
        "lead_arm_angle_at_P7",
        "spine_angle_change_P1_to_P4",
        "spine_angle_change_P1_to_P7",
    )

    def extract(
        self,
        pose_landmarks: np.ndarray,
        checkpoints: dict[str, int],
        handedness: Handedness = Handedness.RIGHT_HANDED,
    ) -> dict[str, float]:
        out: dict[str, float] = {}

        # Spine angles at P1, P4, P7.
        for cp_name in ("P1", "P4", "P7"):
            frame = checkpoints[cp_name]
            out[f"spine_angle_at_{cp_name}"] = self._spine_angle(
                pose_landmarks, frame, handedness,
            )

        # Knee flex — both sides at P1.
        p1_frame = checkpoints["P1"]
        out["knee_flex_lead_at_P1"] = self._knee_flex(
            pose_landmarks, p1_frame, "lead", handedness,
        )
        out["knee_flex_trail_at_P1"] = self._knee_flex(
            pose_landmarks, p1_frame, "trail", handedness,
        )

        # Lead elbow / arm angles at P4 and P7.
        out["lead_elbow_angle_at_P4"] = self._lead_arm_angle(
            pose_landmarks, checkpoints["P4"], handedness,
        )
        out["lead_arm_angle_at_P7"] = self._lead_arm_angle(
            pose_landmarks, checkpoints["P7"], handedness,
        )

        # Deltas: spine-angle changes across checkpoints.
        p1_spine = out["spine_angle_at_P1"]
        p4_spine = out["spine_angle_at_P4"]
        p7_spine = out["spine_angle_at_P7"]
        # Subtraction propagates NaN cleanly if either endpoint is missing.
        out["spine_angle_change_P1_to_P4"] = p4_spine - p1_spine
        out["spine_angle_change_P1_to_P7"] = p7_spine - p1_spine

        return out

    @staticmethod
    def _spine_angle(
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
    ) -> float:
        """
        Unsigned angle in degrees between the mid-hip to mid-shoulder
        vector and world-vertical.

        Returns NaN if any of the four required landmarks are missing.
        """
        lead_hip = pose_landmarks[frame, lead("hip", handedness)]
        trail_hip = pose_landmarks[frame, trail("hip", handedness)]
        lead_shoulder = pose_landmarks[frame, lead("shoulder", handedness)]
        trail_shoulder = pose_landmarks[frame, trail("shoulder", handedness)]

        if not is_valid(lead_hip, trail_hip, lead_shoulder, trail_shoulder):
            return float("nan")

        hip_mid = midpoint(lead_hip, trail_hip)
        shoulder_mid = midpoint(lead_shoulder, trail_shoulder)

        # Vector from hip to shoulder. In image coords, "up in the world"
        # is negative-y, so a perfectly vertical spine has a vector of
        # (0, negative). We compute the angle between this vector and
        # the world-vertical direction (0, -1).
        spine_vec = shoulder_mid - hip_mid
        vertical = np.array([0.0, -1.0])

        n1 = np.linalg.norm(spine_vec)
        n2 = np.linalg.norm(vertical)
        if n1 == 0 or n2 == 0:
            return float("nan")

        cos_theta = np.dot(spine_vec, vertical) / (n1 * n2)
        cos_theta = np.clip(cos_theta, -1.0, 1.0)
        return float(math.degrees(math.acos(cos_theta)))

    @staticmethod
    def _knee_flex(
        pose_landmarks: np.ndarray,
        frame: int,
        side: str,  # "lead" or "trail"
        handedness: Handedness,
    ) -> float:
        """
        Interior angle at the knee: hip -> knee -> ankle.

        180 degrees = leg fully extended; smaller = more flexion.
        """
        resolver = lead if side == "lead" else trail
        hip = pose_landmarks[frame, resolver("hip", handedness)]
        knee = pose_landmarks[frame, resolver("knee", handedness)]
        ankle = pose_landmarks[frame, resolver("ankle", handedness)]
        return angle_at_joint(hip, knee, ankle)

    @staticmethod
    def _lead_arm_angle(
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
    ) -> float:
        """
        Interior angle at the lead elbow: shoulder -> elbow -> wrist.

        180 = arm straight; smaller = bent (collapsed radius / chicken wing).
        Uses lead-side landmarks; visibility caveats apply.
        """
        shoulder = pose_landmarks[frame, lead("shoulder", handedness)]
        elbow = pose_landmarks[frame, lead("elbow", handedness)]
        wrist = pose_landmarks[frame, lead("wrist", handedness)]
        return angle_at_joint(shoulder, elbow, wrist)