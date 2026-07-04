"""
Geometric primitives for feature extraction.

Every per-swing feature ultimately reduces to one of a small set of
geometric operations: an interior angle at a joint, a signed angle
between two vectors, a 2D distance, a midpoint, a signed displacement
along a chosen axis. This module is the toolkit; the extractors are
the consumers.

Conventions
-----------
- Inputs are 2D points by default (x, y). All MediaPipe landmarks are
  passed in as length-2 or length-4 arrays; helpers slice the first two
  channels themselves. The z channel is ignored except where explicitly
  noted.
- y increases downward (image coordinates), so "higher in the world"
  means "smaller y." Helpers that care about vertical direction wrap
  this so individual extractors don't have to.
- Angles are returned in degrees, not radians. KB thresholds will be
  written in degrees.
- NaN propagates: if any input contains NaN, the output is NaN. Frames
  with missing pose detection are NaN-filled upstream, and feature
  extractors should treat NaN outputs as "feature unavailable for this
  frame" rather than zero.
"""

from __future__ import annotations

import numpy as np


def _xy(point: np.ndarray) -> np.ndarray:
    """Slice off just the (x, y) channels, ignoring z / visibility if present."""
    return np.asarray(point, dtype=np.float64)[..., :2]


def distance(a: np.ndarray, b: np.ndarray) -> float:
    """Euclidean 2D distance between two points."""
    a2 = _xy(a)
    b2 = _xy(b)
    return float(np.linalg.norm(a2 - b2))


def midpoint(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The point halfway between a and b, as a length-2 array."""
    a2 = _xy(a)
    b2 = _xy(b)
    return (a2 + b2) / 2.0


def angle_at_joint(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """
    Interior angle in degrees at point `b`, formed by segments b→a and b→c.

    Used for joint flex angles: lead elbow angle is the angle at the
    elbow between the shoulder and the wrist; knee flex is the angle
    at the knee between the hip and the ankle.

    Returns NaN if any input is NaN or if a coincides with b or c.
    """
    a2, b2, c2 = _xy(a), _xy(b), _xy(c)
    v1 = a2 - b2
    v2 = c2 - b2

    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 == 0 or n2 == 0:
        return float("nan")

    cos_theta = np.dot(v1, v2) / (n1 * n2)
    # Guard against floating-point drift outside [-1, 1].
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_theta)))


def signed_angle_2d(v1: np.ndarray, v2: np.ndarray) -> float:
    """
    Signed angle in degrees from vector v1 to vector v2.

    Positive when the rotation from v1 to v2 is counter-clockwise in
    screen coordinates (remembering that y increases downward, so
    "counter-clockwise on screen" looks like "clockwise in the world").
    The sign convention is consistent; individual features decide which
    direction means what.

    Used for wrist cup/bow: a cupped wrist and a bowed wrist have the
    same magnitude with opposite signs, which a plain interior angle
    can't express.

    Returns NaN if either input is zero-length or contains NaN.
    """
    v1 = _xy(v1)
    v2 = _xy(v2)
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 == 0 or n2 == 0:
        return float("nan")

    # atan2 of the cross product over the dot product gives signed angle.
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    return float(np.degrees(np.arctan2(cross, dot)))


def horizontal_displacement(point: np.ndarray, reference: np.ndarray) -> float:
    """
    Signed horizontal displacement of `point` from `reference`.

    Positive = point is to the right of reference in image coordinates.
    Negative = point is to the left.

    Note: "right of reference in image" is not the same as "toward target"
    or "toward camera" — those depend on camera angle and handedness.
    Features that care about direction-of-target should use
    `displacement_toward_lead_side` instead, which is camera-agnostic.
    """
    return float(_xy(point)[0] - _xy(reference)[0])


def vertical_displacement(point: np.ndarray, reference: np.ndarray) -> float:
    """
    Signed vertical displacement of `point` from `reference`, with positive = up.

    Wraps the y-increases-downward convention: the raw image-y delta is
    negated so that "higher in the world" gives a positive value.
    """
    return float(_xy(reference)[1] - _xy(point)[1])


def displacement_toward_lead_side(
    point: np.ndarray,
    reference: np.ndarray,
    lead_foot: np.ndarray,
    trail_foot: np.ndarray,
) -> float:
    """
    Signed displacement of `point` from `reference`, projected onto the
    axis running from trail foot to lead foot.

    Positive = movement toward the lead-foot side.
    Negative = movement toward the trail-foot side.

    This is the workhorse for "head moved toward target" (positive =
    toward target = reverse pivot direction), "hips moved toward ball"
    (positive = lead-side drift, often part of the early-extension
    pattern in a down-the-line view), and any other feature framed in
    terms of target-line direction.

    Using the foot axis as the reference direction makes the measurement
    camera-agnostic: it doesn't matter whether the down-the-line camera
    is set up perfectly behind the player, only that we can see both
    feet.

    Returns NaN if any input is NaN or if the feet coincide.
    """
    lead_xy = _xy(lead_foot)
    trail_xy = _xy(trail_foot)
    axis = lead_xy - trail_xy
    axis_norm = np.linalg.norm(axis)
    if axis_norm == 0:
        return float("nan")
    axis_unit = axis / axis_norm

    delta = _xy(point) - _xy(reference)
    return float(np.dot(delta, axis_unit))


def is_valid(*points: np.ndarray) -> bool:
    """
    True if every point passed in has finite x and y. Helper to let
    extractors fail fast when a feature can't be computed.
    """
    for p in points:
        if not np.all(np.isfinite(_xy(p))):
            return False
    return True


def low_visibility(
    *points: np.ndarray,
    threshold: float = 0.5,
) -> bool:
    """
    True if any of the supplied landmarks has visibility below `threshold`.

    Each point must include the visibility channel (length-4 input from
    a MediaPipe landmarks array). Features that care about confidence
    can call this to flag a computed value as low-confidence.

    Returns False if any point doesn't include a visibility channel —
    visibility info is optional, not required.
    """
    from .landmarks import VISIBILITY

    for p in points:
        arr = np.asarray(p)
        if arr.shape[-1] <= VISIBILITY:
            continue
        v = arr[..., VISIBILITY]
        if np.any(v < threshold):
            return True
    return False