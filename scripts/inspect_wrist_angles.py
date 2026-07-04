"""
Wrist-angle inspection on fault-demo dataset.

Compares cupped-lead and bowed-lead demos at P4 and P7, to validate
that the trail-wrist measurement (visibility-robust from down-the-line)
reliably distinguishes the two patterns.

The decision to use trail-side as primary depends on this check
returning clean, separable values. If trail-wrist at P4 is strongly
positive for cupped demos and strongly negative for bowed demos, the
design is validated and we move on to writing the wrist extractor.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from golf_diagnostic.features import primitives as p
from golf_diagnostic.features.landmarks import Handedness, lead, trail
from golf_diagnostic.pose.extractor import load_pose


REPO_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = REPO_ROOT / "data" / "processed" / "segmentation_summary.txt"
POSE_DIR = REPO_ROOT / "data" / "processed"


def parse_summary() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    pattern = re.compile(
        r"(swing_\d+).*?P1=\s*(\d+).*?P4=\s*(\d+).*?P7=\s*(\d+).*?P10=\s*(\d+)"
    )
    with open(SUMMARY_PATH) as f:
        for line in f:
            m = pattern.search(line)
            if not m:
                continue
            swing_id, p1, p4, p7, p10 = m.groups()
            out[swing_id] = {
                "P1": int(p1), "P4": int(p4), "P7": int(p7), "P10": int(p10),
            }
    return out


def wrist_angle(
    landmarks: np.ndarray,
    frame: int,
    side: str,
    handedness: Handedness = Handedness.RIGHT_HANDED,
) -> tuple[float, float]:
    resolver = lead if side == "lead" else trail
    elbow = landmarks[frame, resolver("elbow", handedness)]
    wrist = landmarks[frame, resolver("wrist", handedness)]
    hand = landmarks[frame, resolver("index", handedness)]

    if not p.is_valid(elbow, wrist, hand):
        return float("nan"), float("nan")

    forearm = wrist[:2] - elbow[:2]
    hand_vec = hand[:2] - wrist[:2]
    angle = p.signed_angle_2d(forearm, hand_vec)
    min_vis = float(min(elbow[3], wrist[3], hand[3]))
    return angle, min_vis


# Group swings by intended cause for direct comparison.
GROUPS = {
    "cupped_at_top": ["swing_16", "swing_31"],         # demo + optional dup
    "bowed_at_top":  ["swing_17", "swing_32"],
    "scoop_at_impact":   ["swing_18", "swing_33"],
    "hold_off_at_impact": ["swing_19", "swing_34"],
    "baseline_normal":   ["swing_09", "swing_15"],     # for reference
}


def inspect_p7_window(swing_id: str, summary: dict[str, dict[str, int]]) -> None:
    pose_path = POSE_DIR / f"{swing_id}_pose.npz"
    if not pose_path.exists():
        return
    pose = load_pose(pose_path)
    p7 = summary[swing_id]["P7"]
    print(f"\n{swing_id}: P7 = frame {p7}")
    print(f"  {'frame':<6} {'offset':<8} {'trail_ang':<12} {'trail_vis':<10}")
    for offset in range(-5, 6):
        frame = p7 + offset
        if frame < 0 or frame >= pose.n_frames:
            continue
        ang, vis = wrist_angle(pose.landmarks, frame, "trail")
        marker = "  <-- P7" if offset == 0 else ""
        print(f"  {frame:<6} {offset:+<8} {ang:>8.2f}    {vis:>6.2f}{marker}")


def main() -> None:
    summary = parse_summary()
    print("=== P7-window inspection for scoop and hold-off demos ===")
    for swing_id in ("swing_18", "swing_19"):
        inspect_p7_window(swing_id, summary)
    # Also include a baseline to compare:
    print("\n=== baseline (clean strike) for comparison ===")
    inspect_p7_window("swing_15", summary)


if __name__ == "__main__":
    main()