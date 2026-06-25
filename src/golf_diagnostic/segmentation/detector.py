"""
Rule-based segmentation of golf swings into P1, P4, P7, P10 checkpoints.

Detection operates on smoothed scalar time series derived from pose
landmarks — primarily wrist height and velocity. Each checkpoint is
detected independently, then ordering constraints are verified.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from golf_diagnostic.pose.extractor import PoseData

# Landmark indices (same as visualizer; could be shared via a constants module later).
LEFT_WRIST, RIGHT_WRIST = 15, 16

# Detection tuning knobs. These are starting values; expect to tune.

SMOOTH_WINDOW = 5
P1_SEARCH_FRACTION = 0.50
P1_VELOCITY_THRESHOLD = 0.002    # normalized y-units per frame
P1_STABILITY_FRAMES = 3
P10_VELOCITY_THRESHOLD = 0.003
P10_STABILITY_FRAMES = 3
P1_TAKEAWAY_VELOCITY_THRESHOLD = 0.005
P1_TAKEAWAY_SUSTAIN_FRAMES = 4 
EXTREMUM_PROMINENCE = 0.05        # minimum height of peak/trough above surrounding noise
EXTREMUM_SUSTAIN_FRAMES = 3       # frames of reversal required to confirm a peak/trough
P4_SEARCH_FRACTION_MAX = 0.70     # extend P4 search window vs. the old 0.60


@dataclass
class SwingSegmentation:
    """Frame indices of the four detected checkpoints, with confidences."""

    p1: int
    p4: int
    p7: int
    p10: int
    p1_confidence: float
    p4_confidence: float
    p7_confidence: float
    p10_confidence: float
    success: bool        # False if ordering constraint failed
    failure_reason: str  # empty string if success


def _smooth(signal: np.ndarray, window: int) -> np.ndarray:
    """Centered moving average, edges padded by reflection."""
    if window <= 1:
        return signal
    pad = window // 2
    padded = np.pad(signal, pad, mode="reflect")
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="valid")


def _compute_signals(pose_data: PoseData) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute (wrist_height, wrist_velocity, wrist_x_position) over time.

    Returns three 1D arrays of length n_frames. NaN frames are linearly
    interpolated so downstream processing has a continuous signal.
    """
    landmarks = pose_data.landmarks  # (n_frames, 33, 4)
    # Mean of left and right wrist; y is image-down so negate for intuition.
    wrist_y = -(landmarks[:, LEFT_WRIST, 1] + landmarks[:, RIGHT_WRIST, 1]) / 2.0
    wrist_x = (landmarks[:, LEFT_WRIST, 0] + landmarks[:, RIGHT_WRIST, 0]) / 2.0

    # Fill NaN frames by linear interpolation.
    wrist_y = _interpolate_nans(wrist_y)
    wrist_x = _interpolate_nans(wrist_x)

    wrist_y_smooth = _smooth(wrist_y, SMOOTH_WINDOW)
    wrist_x_smooth = _smooth(wrist_x, SMOOTH_WINDOW)
    # Velocity as absolute frame-to-frame change.
    wrist_vel = np.abs(np.diff(wrist_y_smooth, prepend=wrist_y_smooth[0]))

    return wrist_y_smooth, wrist_vel, wrist_x_smooth


def _interpolate_nans(arr: np.ndarray) -> np.ndarray:
    """Linearly interpolate over NaN values in a 1D array."""
    nans = np.isnan(arr)
    if not nans.any():
        return arr
    if nans.all():
        return np.zeros_like(arr)
    x = np.arange(len(arr))
    arr = arr.copy()
    arr[nans] = np.interp(x[nans], x[~nans], arr[~nans])
    return arr

def _find_next_local_max(
    signal: np.ndarray,
    start: int,
    end: int,
    min_prominence: float,
    sustain_frames: int,
) -> tuple[int, float]:
    """
    Walk forward from `start` to `end` looking for the first local maximum
    that is at least `min_prominence` above the preceding minimum and is
    followed by `sustain_frames` of sustained descent.

    Returns (frame_index, confidence) where confidence is based on how
    prominent the peak is. Falls back to global max in [start, end) if no
    qualifying peak is found.
    """
    if end <= start + 1:
        return start, 0.0

    recent_min = signal[start]
    candidate_idx = start
    candidate_val = signal[start]

    for i in range(start + 1, end):
        if signal[i] > candidate_val:
            candidate_val = signal[i]
            candidate_idx = i
        elif signal[i] < recent_min:
            recent_min = signal[i]

        # Check whether candidate_val is now a confirmed peak.
        prominence = candidate_val - recent_min
        if prominence >= min_prominence:
            # Look ahead for sustained descent.
            ahead_end = min(i + sustain_frames + 1, end)
            ahead = signal[i + 1:ahead_end]
            if len(ahead) >= sustain_frames and np.all(ahead < candidate_val):
                confidence = float(np.clip(prominence / (2 * min_prominence), 0.0, 1.0))
                return candidate_idx, confidence

    # No qualifying peak found — fall back to global max in window.
    window = signal[start:end]
    fallback_idx = start + int(np.argmax(window))
    return fallback_idx, 0.2


def _find_next_local_min(
    signal: np.ndarray,
    start: int,
    end: int,
    min_prominence: float,
    sustain_frames: int,
) -> tuple[int, float]:
    """Mirror of _find_next_local_max for troughs."""
    if end <= start + 1:
        return start, 0.0

    recent_max = signal[start]
    candidate_idx = start
    candidate_val = signal[start]

    for i in range(start + 1, end):
        if signal[i] < candidate_val:
            candidate_val = signal[i]
            candidate_idx = i
        elif signal[i] > recent_max:
            recent_max = signal[i]

        prominence = recent_max - candidate_val
        if prominence >= min_prominence:
            ahead_end = min(i + sustain_frames + 1, end)
            ahead = signal[i + 1:ahead_end]
            if len(ahead) >= sustain_frames and np.all(ahead > candidate_val):
                confidence = float(np.clip(prominence / (2 * min_prominence), 0.0, 1.0))
                return candidate_idx, confidence

    window = signal[start:end]
    fallback_idx = start + int(np.argmin(window))
    return fallback_idx, 0.2

def _detect_p1(
    wrist_height: np.ndarray, wrist_vel: np.ndarray, n_frames: int
) -> tuple[int, float]:
    """
    Find the start of the takeaway, then back up to the last quiet frame.

    Walks forward through velocity looking for sustained motion above
    P1_TAKEAWAY_VELOCITY_THRESHOLD. The frame just before sustained motion
    begins is P1. Falls back to the original 'sustained low velocity'
    heuristic if no clear takeaway is detected in the search window.
    """
    search_end = max(int(n_frames * P1_SEARCH_FRACTION), P1_STABILITY_FRAMES + 1)

    # Walk forward looking for the start of sustained motion.
    takeaway_start = None
    for i in range(P1_STABILITY_FRAMES, search_end - P1_TAKEAWAY_SUSTAIN_FRAMES):
        window = wrist_vel[i:i + P1_TAKEAWAY_SUSTAIN_FRAMES]
        if np.all(window > P1_TAKEAWAY_VELOCITY_THRESHOLD):
            takeaway_start = i
            break

    if takeaway_start is not None:
        # P1 is the last frame *before* sustained motion. Step back to the
        # most recent frame with velocity below the quiet threshold.
        p1 = takeaway_start - 1
        while p1 > 0 and wrist_vel[p1] >= P1_VELOCITY_THRESHOLD:
            p1 -= 1
        # Confidence: how quiet the frames just before P1 are.
        pre_window = wrist_vel[max(p1 - P1_STABILITY_FRAMES, 0):p1 + 1]
        if len(pre_window) > 0:
            confidence = float(np.clip(
                1.0 - pre_window.mean() / P1_VELOCITY_THRESHOLD, 0.0, 1.0
            ))
        else:
            confidence = 0.5
        return p1, confidence

    # Fallback: no clear takeaway found. Use the original heuristic.
    candidates = []
    for i in range(P1_STABILITY_FRAMES, search_end):
        window = wrist_vel[i - P1_STABILITY_FRAMES:i]
        if np.all(window < P1_VELOCITY_THRESHOLD):
            candidates.append(i)

    if not candidates:
        p1 = int(np.argmin(wrist_vel[:search_end]))
        confidence = 0.3
    else:
        p1 = candidates[-1]
        vel_at_p1 = wrist_vel[max(p1 - P1_STABILITY_FRAMES, 0):p1].mean()
        confidence = float(np.clip(1.0 - vel_at_p1 / P1_VELOCITY_THRESHOLD, 0.0, 1.0))
    return p1, confidence


def _detect_p4(
    wrist_height: np.ndarray, p1: int, n_frames: int
) -> tuple[int, float]:
    """First local maximum of wrist height after P1 — top of the backswing."""
    search_end = min(int(n_frames * P4_SEARCH_FRACTION_MAX), n_frames)
    return _find_next_local_max(
        wrist_height,
        start=p1 + 1,
        end=search_end,
        min_prominence=EXTREMUM_PROMINENCE,
        sustain_frames=EXTREMUM_SUSTAIN_FRAMES,
    )


def _detect_p7(
    wrist_height: np.ndarray, wrist_vel: np.ndarray, p4: int, n_frames: int
) -> tuple[int, float]:
    """First local minimum of wrist height after P4 — impact."""
    p7, base_confidence = _find_next_local_min(
        wrist_height,
        start=p4 + 1,
        end=n_frames,
        min_prominence=EXTREMUM_PROMINENCE,
        sustain_frames=EXTREMUM_SUSTAIN_FRAMES,
    )

    # Velocity sanity check: impact should have high velocity.
    post_p4_vel = wrist_vel[p4:]
    if len(post_p4_vel) == 0 or p7 >= n_frames:
        return p7, 0.0
    vel_at_p7 = wrist_vel[p7]
    max_vel = post_p4_vel.max()
    velocity_score = float(vel_at_p7 / (max_vel + 1e-6))

    # Blend the prominence-based confidence with the velocity score.
    confidence = (base_confidence + velocity_score) / 2.0
    return p7, confidence


def _detect_p10(
    wrist_height: np.ndarray, wrist_vel: np.ndarray, p7: int, n_frames: int
) -> tuple[int, float]:
    """First frame after P7 where hands are high and velocity is low."""
    if p7 + P10_STABILITY_FRAMES >= n_frames:
        return n_frames - 1, 0.0

    # The finish should have hands above the median height of the post-P7 window.
    post_p7_height = wrist_height[p7:]
    height_threshold = np.median(post_p7_height) + 0.5 * (
        post_p7_height.max() - np.median(post_p7_height)
    )

    for i in range(p7 + P10_STABILITY_FRAMES, n_frames):
        vel_window = wrist_vel[i - P10_STABILITY_FRAMES:i]
        if (np.all(vel_window < P10_VELOCITY_THRESHOLD)
                and wrist_height[i] > height_threshold):
            vel_score = 1.0 - vel_window.mean() / P10_VELOCITY_THRESHOLD
            confidence = float(np.clip(vel_score, 0.0, 1.0))
            return i, confidence

    # Fall back to the last frame.
    return n_frames - 1, 0.2


def segment_swing(pose_data: PoseData) -> SwingSegmentation:
    """
    Detect P1, P4, P7, P10 frame indices from a pose-extracted swing.

    Returns a SwingSegmentation with success=False if the ordering
    constraint p1 < p4 < p7 < p10 is violated.
    """
    n_frames = pose_data.n_frames
    if n_frames < 10:
        return SwingSegmentation(
            p1=0, p4=0, p7=0, p10=0,
            p1_confidence=0.0, p4_confidence=0.0,
            p7_confidence=0.0, p10_confidence=0.0,
            success=False, failure_reason="Too few frames",
        )

    wrist_height, wrist_vel, _ = _compute_signals(pose_data)

    p1, p1_conf = _detect_p1(wrist_height, wrist_vel, n_frames)
    p4, p4_conf = _detect_p4(wrist_height, p1, n_frames)
    p7, p7_conf = _detect_p7(wrist_height, wrist_vel, p4, n_frames)
    p10, p10_conf = _detect_p10(wrist_height, wrist_vel, p7, n_frames)

    success = p1 < p4 < p7 < p10
    failure_reason = "" if success else f"Ordering violated: P1={p1}, P4={p4}, P7={p7}, P10={p10}"

    return SwingSegmentation(
        p1=p1, p4=p4, p7=p7, p10=p10,
        p1_confidence=p1_conf, p4_confidence=p4_conf,
        p7_confidence=p7_conf, p10_confidence=p10_conf,
        success=success, failure_reason=failure_reason,
    )