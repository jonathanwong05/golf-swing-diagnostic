"""
Named MediaPipe Pose landmark indices and lead/trail-side resolution.

MediaPipe returns 33 landmarks per frame, indexed 0-32. This module
gives them names and provides a small helper that maps "lead" / "trail"
to the correct left/right index based on the golfer's handedness.

Every feature in the inventory is defined in lead-side / trail-side
terms (lead wrist, trail elbow, etc.) rather than left/right, so all
feature extractors should go through `lead()` / `trail()` rather than
referencing left/right landmarks directly.
"""

from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# MediaPipe Pose landmark indices.
# Full list at https://google.github.io/mediapipe/solutions/pose.html
# Only the ones we actually use are named below; add more as needed.
# ---------------------------------------------------------------------------

NOSE = 0

LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_PINKY = 17
RIGHT_PINKY = 18
LEFT_INDEX = 19
RIGHT_INDEX = 20
LEFT_THUMB = 21
RIGHT_THUMB = 22

LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28
LEFT_HEEL = 29
RIGHT_HEEL = 30
LEFT_FOOT_INDEX = 31
RIGHT_FOOT_INDEX = 32


# ---------------------------------------------------------------------------
# Coordinate channel indices into the (33, 4) per-frame array.
# ---------------------------------------------------------------------------

X = 0
Y = 1
Z = 2
VISIBILITY = 3


# ---------------------------------------------------------------------------
# Handedness.
# ---------------------------------------------------------------------------

class Handedness(Enum):
    """Which side the golfer leads with."""

    RIGHT_HANDED = "right"  # lead = left side of body
    LEFT_HANDED = "left"    # lead = right side of body


# Logical joint names. Each maps to (right_handed_index, left_handed_index)
# — the lead-side index for each handedness.
_LEAD_LOOKUP = {
    "shoulder":   (LEFT_SHOULDER,   RIGHT_SHOULDER),
    "elbow":      (LEFT_ELBOW,      RIGHT_ELBOW),
    "wrist":      (LEFT_WRIST,      RIGHT_WRIST),
    "pinky":      (LEFT_PINKY,      RIGHT_PINKY),
    "index":      (LEFT_INDEX,      RIGHT_INDEX),
    "thumb":      (LEFT_THUMB,      RIGHT_THUMB),
    "hip":        (LEFT_HIP,        RIGHT_HIP),
    "knee":       (LEFT_KNEE,       RIGHT_KNEE),
    "ankle":      (LEFT_ANKLE,      RIGHT_ANKLE),
    "heel":       (LEFT_HEEL,       RIGHT_HEEL),
    "foot_index": (LEFT_FOOT_INDEX, RIGHT_FOOT_INDEX),
}


def lead(joint: str, handedness: Handedness = Handedness.RIGHT_HANDED) -> int:
    """
    Return the landmark index for the lead-side version of `joint`.

    For a right-handed golfer, lead = left side; for a left-handed golfer,
    lead = right side.

    >>> lead("wrist", Handedness.RIGHT_HANDED) == LEFT_WRIST
    True
    >>> lead("wrist", Handedness.LEFT_HANDED) == RIGHT_WRIST
    True
    """
    if joint not in _LEAD_LOOKUP:
        raise KeyError(f"Unknown joint name: {joint!r}")
    right_handed_idx, left_handed_idx = _LEAD_LOOKUP[joint]
    return right_handed_idx if handedness == Handedness.RIGHT_HANDED else left_handed_idx


def trail(joint: str, handedness: Handedness = Handedness.RIGHT_HANDED) -> int:
    """
    Return the landmark index for the trail-side version of `joint`.

    The mirror of `lead()`.
    """
    if joint not in _LEAD_LOOKUP:
        raise KeyError(f"Unknown joint name: {joint!r}")
    right_handed_idx, left_handed_idx = _LEAD_LOOKUP[joint]
    # Trail is the opposite of lead.
    return left_handed_idx if handedness == Handedness.RIGHT_HANDED else right_handed_idx