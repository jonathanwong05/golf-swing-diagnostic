"""
Position-category features: head/hip displacements, hand-to-body
distance, stance width, and ankle displacement.

All spatial features are normalized by ankle-to-hip vertical distance
at P1 (same body-scale reference as the rotation extractor — see
extractors/rotation.py for the rationale). Target-axis displacements
are projected onto the trail-ankle -> lead-ankle unit vector at P1,
which resolves the axis per-swing and is camera-agnostic (uses the
same primitive philosophy as displacement_toward_lead_side).

The head/hip P1->P7 measurements are split into two features each:
    - target-axis component: signed displacement toward/away from target
    - vertical component: image-y change, sign-flipped so raised = positive
See docs/phase2_notes.md for why the split is diagnostically necessary.
"""

from __future__ import annotations

import numpy as np

from ..landmarks import Handedness, NOSE, lead, trail
from ..primitives import (
    displacement_toward_lead_side,
    distance,
    is_valid,
    midpoint,
    vertical_displacement,
)


# Same threshold as rotation extractor: ankle-to-hip vertical below
# this suggests degenerate pose or bad framing.
_MIN_REFERENCE_LENGTH = 0.05


class PositionExtractor:
    """Head/hip displacements, hand distance from body, stance width, ankle displacement."""

    FEATURES = (
        "head_displacement_P1_to_P4",
        "head_displacement_P1_to_P7_target_axis",
        "head_vertical_change_P1_to_P7",
        "hip_displacement_P1_to_P7_target_axis",
        "hip_vertical_change_P1_to_P7",
        "hand_distance_from_body_at_P1",
        "hand_distance_from_body_at_P7",
        "stance_width_at_P1",
        "ankle_displacement_at_P7",
    )

    def extract(
        self,
        pose_landmarks: np.ndarray,
        checkpoints: dict[str, int],
        handedness: Handedness = Handedness.RIGHT_HANDED,
    ) -> dict[str, float]:
        out: dict[str, float] = {}

        p1 = checkpoints["P1"]
        p4 = checkpoints["P4"]
        p7 = checkpoints["P7"]

        # Body-scale reference at P1.
        reference_length = self._body_reference_length(pose_landmarks, p1, handedness)

        # Ankles at P1 anchor the target axis.
        lead_ankle_p1 = pose_landmarks[p1, lead("ankle", handedness)]
        trail_ankle_p1 = pose_landmarks[p1, trail("ankle", handedness)]

        # ---- Head target-axis displacements (need ankles at P1) ----
        nose_p1 = pose_landmarks[p1, NOSE]
        nose_p4 = pose_landmarks[p4, NOSE]
        nose_p7 = pose_landmarks[p7, NOSE]

        out["head_displacement_P1_to_P4"] = self._target_axis_displacement(
            nose_p4, nose_p1, lead_ankle_p1, trail_ankle_p1, reference_length,
        )
        out["head_displacement_P1_to_P7_target_axis"] = self._target_axis_displacement(
            nose_p7, nose_p1, lead_ankle_p1, trail_ankle_p1, reference_length,
        )

        # ---- Head vertical change P1 -> P7 ----
        out["head_vertical_change_P1_to_P7"] = self._vertical_change(
            nose_p7, nose_p1, reference_length,
        )

        # ---- Hip midpoints ----
        lead_hip_p1 = pose_landmarks[p1, lead("hip", handedness)]
        trail_hip_p1 = pose_landmarks[p1, trail("hip", handedness)]
        lead_hip_p7 = pose_landmarks[p7, lead("hip", handedness)]
        trail_hip_p7 = pose_landmarks[p7, trail("hip", handedness)]

        hip_mid_p1 = midpoint(lead_hip_p1, trail_hip_p1) if is_valid(lead_hip_p1, trail_hip_p1) else None
        hip_mid_p7 = midpoint(lead_hip_p7, trail_hip_p7) if is_valid(lead_hip_p7, trail_hip_p7) else None

        out["hip_displacement_P1_to_P7_target_axis"] = self._target_axis_displacement(
            hip_mid_p7, hip_mid_p1, lead_ankle_p1, trail_ankle_p1, reference_length,
        ) if hip_mid_p1 is not None and hip_mid_p7 is not None else float("nan")

        out["hip_vertical_change_P1_to_P7"] = self._vertical_change(
            hip_mid_p7, hip_mid_p1, reference_length,
        ) if hip_mid_p1 is not None and hip_mid_p7 is not None else float("nan")

        # ---- Hand distance from body at P1 and P7 ----
        out["hand_distance_from_body_at_P1"] = self._hand_distance_from_torso(
            pose_landmarks, p1, handedness, reference_length,
        )
        out["hand_distance_from_body_at_P7"] = self._hand_distance_from_torso(
            pose_landmarks, p7, handedness, reference_length,
        )

        # ---- Stance width at P1 ----
        if is_valid(lead_ankle_p1, trail_ankle_p1) and self._reference_ok(reference_length):
            out["stance_width_at_P1"] = float(
                abs(lead_ankle_p1[0] - trail_ankle_p1[0]) / reference_length
            )
        else:
            out["stance_width_at_P1"] = float("nan")

        # ---- Ankle displacement (mid-ankle vertical change P1 -> P7) ----
        lead_ankle_p7 = pose_landmarks[p7, lead("ankle", handedness)]
        trail_ankle_p7 = pose_landmarks[p7, trail("ankle", handedness)]
        if (
            is_valid(lead_ankle_p1, trail_ankle_p1, lead_ankle_p7, trail_ankle_p7)
            and self._reference_ok(reference_length)
        ):
            ankle_mid_p1 = midpoint(lead_ankle_p1, trail_ankle_p1)
            ankle_mid_p7 = midpoint(lead_ankle_p7, trail_ankle_p7)
            out["ankle_displacement_at_P7"] = float(
                vertical_displacement(ankle_mid_p7, ankle_mid_p1) / reference_length
            )
        else:
            out["ankle_displacement_at_P7"] = float("nan")

        return out

    # -------------------- helpers --------------------

    @staticmethod
    def _reference_ok(reference_length: float) -> bool:
        return np.isfinite(reference_length) and reference_length >= _MIN_REFERENCE_LENGTH

    @staticmethod
    def _body_reference_length(
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
    ) -> float:
        """Vertical distance from mid-ankle to mid-hip at frame. Matches rotation extractor."""
        lead_ankle = pose_landmarks[frame, lead("ankle", handedness)]
        trail_ankle = pose_landmarks[frame, trail("ankle", handedness)]
        lead_hip = pose_landmarks[frame, lead("hip", handedness)]
        trail_hip = pose_landmarks[frame, trail("hip", handedness)]
        if not is_valid(lead_ankle, trail_ankle, lead_hip, trail_hip):
            return float("nan")
        ankle_mid = midpoint(lead_ankle, trail_ankle)
        hip_mid = midpoint(lead_hip, trail_hip)
        return float(abs(ankle_mid[1] - hip_mid[1]))

    @classmethod
    def _target_axis_displacement(
        cls,
        point,
        reference,
        lead_ankle_p1,
        trail_ankle_p1,
        reference_length: float,
    ) -> float:
        """
        Signed displacement of (point - reference) projected onto the
        trail-ankle -> lead-ankle axis at P1, normalized.
        Positive = toward target (lead side).
        """
        if point is None or reference is None:
            return float("nan")
        if not cls._reference_ok(reference_length):
            return float("nan")
        if not is_valid(point, reference, lead_ankle_p1, trail_ankle_p1):
            return float("nan")
        raw = displacement_toward_lead_side(
            point, reference, lead_ankle_p1, trail_ankle_p1,
        )
        if not np.isfinite(raw):
            return float("nan")
        return float(raw / reference_length)

    @classmethod
    def _vertical_change(
        cls,
        point,
        reference,
        reference_length: float,
    ) -> float:
        """
        Signed vertical change from reference to point, sign-flipped so
        raised = positive, normalized by body reference length.
        """
        if point is None or reference is None:
            return float("nan")
        if not cls._reference_ok(reference_length):
            return float("nan")
        if not is_valid(point, reference):
            return float("nan")
        raw = vertical_displacement(point, reference)
        if not np.isfinite(raw):
            return float("nan")
        return float(raw / reference_length)

    @classmethod
    def _hand_distance_from_torso(
        cls,
        pose_landmarks: np.ndarray,
        frame: int,
        handedness: Handedness,
        reference_length: float,
    ) -> float:
        """
        Perpendicular distance from hand midpoint (wrist midpoint) to
        the shoulder-hip line (torso axis), normalized.
        Unsigned magnitude.
        """
        if not cls._reference_ok(reference_length):
            return float("nan")

        lead_wrist = pose_landmarks[frame, lead("wrist", handedness)]
        trail_wrist = pose_landmarks[frame, trail("wrist", handedness)]
        lead_shoulder = pose_landmarks[frame, lead("shoulder", handedness)]
        trail_shoulder = pose_landmarks[frame, trail("shoulder", handedness)]
        lead_hip = pose_landmarks[frame, lead("hip", handedness)]
        trail_hip = pose_landmarks[frame, trail("hip", handedness)]

        if not is_valid(
            lead_wrist, trail_wrist,
            lead_shoulder, trail_shoulder,
            lead_hip, trail_hip,
        ):
            return float("nan")

        hand_mid = midpoint(lead_wrist, trail_wrist)
        shoulder_mid = midpoint(lead_shoulder, trail_shoulder)
        hip_mid = midpoint(lead_hip, trail_hip)

        # Perpendicular distance from hand_mid to the line through
        # shoulder_mid and hip_mid.
        line = hip_mid - shoulder_mid
        line_norm = float(np.linalg.norm(line))
        if line_norm < 1e-8:
            return float("nan")

        rel = hand_mid - shoulder_mid
        # 2D cross product magnitude / line length = perpendicular distance.
        cross = abs(float(line[0] * rel[1] - line[1] * rel[0]))
        return float((cross / line_norm) / reference_length)