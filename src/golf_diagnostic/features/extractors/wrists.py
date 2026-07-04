"""
Wrist-angle features at P1, P4, and P7.

Both lead-side and trail-side angles are computed at each checkpoint,
independent of visibility or handedness. Downstream consumers (the
KB matcher) decide how to weight each side based on measurement
reliability.

Sign convention
---------------
The signed angle is computed from the forearm vector (elbow -> wrist)
to the hand vector (wrist -> index-finger-base). The sign is
consistent across both sides:

    positive  ->  wrist cupped (extended)
    zero      ->  wrist neutral (straight)
    negative  ->  wrist bowed (flexed)

This is validated empirically against the cupped-lead-wrist and
bowed-lead-wrist fault demos at P4. See `docs/phase2_notes.md`.

P5-proxy wrist features are NOT computed here — they belong to the
interpolation module because they combine P4 and P7 values.
"""

from __future__ import annotations

import numpy as np

from ..landmarks import Handedness, lead, trail
from ..primitives import is_valid, signed_angle_2d


class WristExtractor:
    """Compute wrist-angle features at P1, P4, and P7 for one swing."""

    # Feature names this extractor produces. The orchestrator uses
    # this to know what it will get back and to validate coverage
    # against schema.FEATURE_NAMES.
    FEATURES = (
        "lead_wrist_angle_at_P1",
        "trail_wrist_angle_at_P1",
        "lead_wrist_angle_at_P4",
        "trail_wrist_angle_at_P4",
        "lead_wrist_angle_at_P7",
        "trail_wrist_angle_at_P7",
    )

    def extract(
        self,
        pose_landmarks: np.ndarray,
        checkpoints: dict[str, int],
        handedness: Handedness = Handedness.RIGHT_HANDED,
    ) -> dict[str, float]:
        """
        Compute all six wrist features for one swing.

        Parameters
        ----------
        pose_landmarks : ndarray of shape (n_frames, 33, 4)
            MediaPipe landmarks time series. NaN-filled where pose
            detection failed.
        checkpoints : dict
            Mapping like {"P1": 18, "P4": 46, "P7": 62, "P10": 86}.
            Only P1, P4, P7 are read; P10 is ignored here.
        handedness : Handedness
            Whether the golfer is right- or left-handed. Determines
            which physical side is "lead" vs "trail".

        Returns
        -------
        dict[str, float]
            Feature name -> value. NaN where the underlying
            landmarks were missing or the geometry was degenerate.
        """
        out: dict[str, float] = {}
        for cp_name in ("P1", "P4", "P7"):
            frame = checkpoints[cp_name]
            out[f"lead_wrist_angle_at_{cp_name}"] = self._compute(
                pose_landmarks, frame, "lead", handedness,
            )
            out[f"trail_wrist_angle_at_{cp_name}"] = self._compute(
                pose_landmarks, frame, "trail", handedness,
            )
        return out

    @staticmethod
    def _compute(
        pose_landmarks: np.ndarray,
        frame: int,
        side: str,  # "lead" or "trail"
        handedness: Handedness,
    ) -> float:
        """
        Signed angle from forearm to hand at a single frame.

        Returns NaN if any input landmark is NaN or if the geometry
        is degenerate (coincident points).
        """
        resolver = lead if side == "lead" else trail
        elbow = pose_landmarks[frame, resolver("elbow", handedness)]
        wrist = pose_landmarks[frame, resolver("wrist", handedness)]
        hand = pose_landmarks[frame, resolver("index", handedness)]

        if not is_valid(elbow, wrist, hand):
            return float("nan")

        forearm = wrist[:2] - elbow[:2]
        hand_vec = hand[:2] - wrist[:2]
        return signed_angle_2d(forearm, hand_vec)