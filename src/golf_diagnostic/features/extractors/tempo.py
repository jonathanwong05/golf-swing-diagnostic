"""
Tempo features: backswing/downswing ratio and total swing duration.

These are the only two directly-measured (non-proxy) features in the
v1 schema — no landmarks involved, just checkpoint frame indices and
video fps.

Features
--------
tempo_ratio:
    (P4 - P1) / (P7 - P4), computed in frames. Backswing duration
    divided by downswing duration. Unitless — fps cancels out.
    Iron neutral target roughly 3.0. Amateur swings often drift
    toward 2:1 (rushed) or 4:1+ (deliberate/slow).

total_swing_duration:
    (P10 - P1) / fps, in seconds. Whole-swing duration from address
    to finish. Used alongside tempo_ratio for lack-of-distance
    cause 4.

Design notes
------------
- Handedness is irrelevant here (tempo is symmetric under lead/trail
  swap) but accepted for signature uniformity across extractors.

- pose_landmarks is unused but accepted for the same reason. The
  orchestrator can call every extractor with the same argument list.

- fps is optional (default None) rather than required. Extractors
  that don't need it can be called without it in tests. If fps is
  None or non-positive, total_swing_duration returns NaN;
  tempo_ratio is unaffected.

- Degenerate segmentation (P4 == P1 or P7 == P4) returns NaN for
  tempo_ratio rather than dividing by zero. In practice
  SwingSegmentation enforces strict ordering, but the extractor
  takes a raw dict and defends itself.
"""

from __future__ import annotations

import math

import numpy as np

from ..landmarks import Handedness


class TempoExtractor:
    """Whole-swing tempo and duration features."""

    FEATURES = (
        "tempo_ratio",
        "total_swing_duration",
    )

    def extract(
        self,
        pose_landmarks: np.ndarray,
        checkpoints: dict[str, int],
        handedness: Handedness = Handedness.RIGHT_HANDED,
        fps: float | None = None,
    ) -> dict[str, float]:
        p1 = checkpoints["P1"]
        p4 = checkpoints["P4"]
        p7 = checkpoints["P7"]
        p10 = checkpoints["P10"]

        backswing_frames = p4 - p1
        downswing_frames = p7 - p4
        total_frames = p10 - p1

        if backswing_frames <= 0 or downswing_frames <= 0:
            tempo_ratio = float("nan")
        else:
            tempo_ratio = backswing_frames / downswing_frames

        if fps is None or not math.isfinite(fps) or fps <= 0 or total_frames <= 0:
            total_swing_duration = float("nan")
        else:
            total_swing_duration = total_frames / fps

        return {
            "tempo_ratio": tempo_ratio,
            "total_swing_duration": total_swing_duration,
        }