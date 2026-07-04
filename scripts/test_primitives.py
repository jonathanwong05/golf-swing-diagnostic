"""
Sanity check for features.landmarks and features.primitives.

Run from the repo root:
    python scripts/test_primitives.py

Exits with code 0 if all checks pass, 1 if any fail. Prints a summary
of each check so you can eyeball the numbers in addition to the
pass/fail status.
"""

from __future__ import annotations

import math
import sys

import numpy as np

from golf_diagnostic.features import primitives as p
from golf_diagnostic.features.landmarks import (
    LEFT_WRIST,
    RIGHT_WRIST,
    Handedness,
    lead,
    trail,
)


# ---------------------------------------------------------------------------
# Tiny test harness — no pytest dependency, easier to extend ad hoc.
# ---------------------------------------------------------------------------

_results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    _results.append((name, condition, detail))


def approx(actual: float, expected: float, tol: float = 1e-6) -> bool:
    if math.isnan(actual) and math.isnan(expected):
        return True
    return abs(actual - expected) < tol


# ---------------------------------------------------------------------------
# Landmark resolution.
# ---------------------------------------------------------------------------

check(
    "lead('wrist', RIGHT_HANDED) == LEFT_WRIST",
    lead("wrist", Handedness.RIGHT_HANDED) == LEFT_WRIST,
    f"got {lead('wrist', Handedness.RIGHT_HANDED)}",
)
check(
    "trail('wrist', RIGHT_HANDED) == RIGHT_WRIST",
    trail("wrist", Handedness.RIGHT_HANDED) == RIGHT_WRIST,
    f"got {trail('wrist', Handedness.RIGHT_HANDED)}",
)
check(
    "lead('wrist', LEFT_HANDED) == RIGHT_WRIST",
    lead("wrist", Handedness.LEFT_HANDED) == RIGHT_WRIST,
    f"got {lead('wrist', Handedness.LEFT_HANDED)}",
)


# ---------------------------------------------------------------------------
# distance and midpoint.
# ---------------------------------------------------------------------------

a = np.array([0.0, 0.0])
b = np.array([3.0, 4.0])
check("distance((0,0), (3,4)) == 5", approx(p.distance(a, b), 5.0))
check("midpoint((0,0), (3,4)) == (1.5, 2.0)",
      np.allclose(p.midpoint(a, b), [1.5, 2.0]))


# ---------------------------------------------------------------------------
# angle_at_joint.
# ---------------------------------------------------------------------------

# Right angle: shoulder above elbow, wrist to the right of elbow.
shoulder = np.array([0.5, 0.3])
elbow    = np.array([0.5, 0.5])
wrist    = np.array([0.7, 0.5])
ang = p.angle_at_joint(shoulder, elbow, wrist)
check("angle_at_joint right-angle == 90", approx(ang, 90.0, tol=1e-4),
      f"got {ang:.4f}")

# Straight arm: shoulder, elbow, wrist colinear.
shoulder = np.array([0.5, 0.3])
elbow    = np.array([0.5, 0.5])
wrist    = np.array([0.5, 0.7])
ang = p.angle_at_joint(shoulder, elbow, wrist)
check("angle_at_joint straight == 180", approx(ang, 180.0, tol=1e-4),
      f"got {ang:.4f}")

# Slightly bent arm — sanity check for plausibility.
shoulder = np.array([0.5, 0.3])
elbow    = np.array([0.4, 0.5])
wrist    = np.array([0.5, 0.7])
ang = p.angle_at_joint(shoulder, elbow, wrist)
check("angle_at_joint moderately bent gives 120-140",
      120.0 < ang < 140.0, f"got {ang:.4f}")

# Degenerate: coincident points should return NaN, not crash.
ang = p.angle_at_joint(elbow, elbow, wrist)
check("angle_at_joint coincident inputs -> NaN", math.isnan(ang),
      f"got {ang}")

# NaN propagation.
ang = p.angle_at_joint(np.array([np.nan, 0.5]), elbow, wrist)
check("angle_at_joint NaN input -> NaN", math.isnan(ang), f"got {ang}")


# ---------------------------------------------------------------------------
# signed_angle_2d.
# ---------------------------------------------------------------------------

# v1 = right, v2 = down in image coords. cross > 0, so result is +90.
ang = p.signed_angle_2d(np.array([1.0, 0.0]), np.array([0.0, 1.0]))
check("signed_angle_2d right -> down == +90", approx(ang, 90.0, tol=1e-4),
      f"got {ang:.4f}")

# Reverse: down -> right should give -90.
ang = p.signed_angle_2d(np.array([0.0, 1.0]), np.array([1.0, 0.0]))
check("signed_angle_2d down -> right == -90", approx(ang, -90.0, tol=1e-4),
      f"got {ang:.4f}")

# Same vector -> 0.
ang = p.signed_angle_2d(np.array([1.0, 0.0]), np.array([1.0, 0.0]))
check("signed_angle_2d same vector == 0", approx(ang, 0.0, tol=1e-4),
      f"got {ang:.4f}")

# Opposite vectors -> ±180.
ang = p.signed_angle_2d(np.array([1.0, 0.0]), np.array([-1.0, 0.0]))
check("signed_angle_2d opposite ~ ±180", approx(abs(ang), 180.0, tol=1e-4),
      f"got {ang:.4f}")


# ---------------------------------------------------------------------------
# vertical_displacement (y increases downward).
# ---------------------------------------------------------------------------

# Point at y=0.2, reference at y=0.5. Point is higher in the world.
disp = p.vertical_displacement(
    np.array([0.5, 0.2]), np.array([0.5, 0.5])
)
check("vertical_displacement higher point -> positive",
      disp > 0 and approx(disp, 0.3), f"got {disp:.4f}")

# Point lower than reference.
disp = p.vertical_displacement(
    np.array([0.5, 0.8]), np.array([0.5, 0.5])
)
check("vertical_displacement lower point -> negative",
      disp < 0 and approx(disp, -0.3), f"got {disp:.4f}")


# ---------------------------------------------------------------------------
# horizontal_displacement.
# ---------------------------------------------------------------------------

disp = p.horizontal_displacement(
    np.array([0.7, 0.5]), np.array([0.5, 0.5])
)
check("horizontal_displacement right of reference -> positive",
      approx(disp, 0.2), f"got {disp:.4f}")


# ---------------------------------------------------------------------------
# displacement_toward_lead_side.
# ---------------------------------------------------------------------------
# Set up a right-handed golfer: lead foot to the left in image (smaller x),
# trail foot to the right (larger x). For the down-the-line camera that
# captures the player from behind on the trail side, this is the typical
# layout. A point moving toward the lead foot returns a positive value.

lead_foot  = np.array([0.4, 0.9])
trail_foot = np.array([0.6, 0.9])

# Point moved leftward (toward lead foot).
point     = np.array([0.45, 0.5])
reference = np.array([0.50, 0.5])
disp = p.displacement_toward_lead_side(point, reference, lead_foot, trail_foot)
check("displacement_toward_lead_side: leftward shift -> positive",
      disp > 0, f"got {disp:.4f}")

# Point moved rightward (toward trail foot).
point     = np.array([0.55, 0.5])
reference = np.array([0.50, 0.5])
disp = p.displacement_toward_lead_side(point, reference, lead_foot, trail_foot)
check("displacement_toward_lead_side: rightward shift -> negative",
      disp < 0, f"got {disp:.4f}")

# Degenerate feet -> NaN.
disp = p.displacement_toward_lead_side(
    np.array([0.5, 0.5]), np.array([0.5, 0.5]),
    np.array([0.5, 0.9]), np.array([0.5, 0.9]),
)
check("displacement_toward_lead_side: coincident feet -> NaN",
      math.isnan(disp), f"got {disp}")


# ---------------------------------------------------------------------------
# is_valid and low_visibility.
# ---------------------------------------------------------------------------

check("is_valid passes for finite point",
      p.is_valid(np.array([0.5, 0.5, 0.0, 0.9])) is True)
check("is_valid fails for NaN point",
      p.is_valid(np.array([np.nan, 0.5, 0.0, 0.9])) is False)

# low_visibility: a 4-element landmark with visibility 0.3 < 0.5 -> True.
check("low_visibility flags vis=0.3",
      p.low_visibility(np.array([0.5, 0.5, 0.0, 0.3])) is True)
check("low_visibility does not flag vis=0.9",
      p.low_visibility(np.array([0.5, 0.5, 0.0, 0.9])) is False)
# 2D point with no visibility channel -> not flagged.
check("low_visibility ignores 2D-only point",
      p.low_visibility(np.array([0.5, 0.5])) is False)


# ---------------------------------------------------------------------------
# Realistic worked example: lead wrist cup/bow from synthetic landmarks.
# ---------------------------------------------------------------------------
# This mirrors how the wrist extractor will use signed_angle_2d.
# The lead wrist angle is the signed angle from the forearm vector
# (elbow -> wrist) to the hand vector (wrist -> hand-knuckles/index).
# A "cupped" wrist bends the hand back; "bowed" bends it forward.

elbow = np.array([0.50, 0.30])
wrist = np.array([0.50, 0.50])

# Neutral: hand continues straight down from wrist.
hand_neutral = np.array([0.50, 0.70])
forearm = wrist - elbow
hand_vec = hand_neutral - wrist
ang_neutral = p.signed_angle_2d(forearm, hand_vec)
check("wrist neutral ~ 0",
      approx(ang_neutral, 0.0, tol=1e-4), f"got {ang_neutral:.4f}")

# Hand bent toward camera-right (positive in our sign convention).
hand_bent_right = np.array([0.55, 0.68])
hand_vec = hand_bent_right - wrist
ang_right = p.signed_angle_2d(forearm, hand_vec)
check("wrist bent right is nonzero",
      not approx(ang_right, 0.0, tol=1e-2), f"got {ang_right:.4f}")

# Mirror bend -> opposite sign of the same magnitude.
hand_bent_left = np.array([0.45, 0.68])
hand_vec = hand_bent_left - wrist
ang_left = p.signed_angle_2d(forearm, hand_vec)
check("wrist mirror-bent has opposite sign, same magnitude",
      approx(ang_left, -ang_right, tol=1e-4),
      f"right={ang_right:.4f}, left={ang_left:.4f}")


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------

n_pass = sum(1 for _, ok, _ in _results if ok)
n_fail = len(_results) - n_pass

print(f"\n{'name':<60} status   detail")
print("-" * 90)
for name, ok, detail in _results:
    status = "PASS" if ok else "FAIL"
    print(f"{name:<60} {status:<8} {detail}")

print(f"\n{n_pass}/{len(_results)} passed")
sys.exit(0 if n_fail == 0 else 1)