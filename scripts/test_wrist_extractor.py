"""
Sanity check for WristExtractor.

Runs the extractor over key swings (baselines and fault demos) and
prints the produced feature dict. Compares against known-expected
patterns from the inspection work:

  swing_16 (cupped_at_top):    trail_wrist_angle_at_P4 strongly positive (~+52)
  swing_17 (bowed_at_top):     trail_wrist_angle_at_P4 near zero or negative
  swing_09 (normal, cupping):  moderate values
  swing_15 (clean strike):     moderate values

Also verifies the extractor produces the six expected keys and no
extras, and that NaN propagates cleanly when a checkpoint frame has
missing landmarks (synthetic test at the end).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from golf_diagnostic.features.extractors.wrists import WristExtractor
from golf_diagnostic.features.landmarks import Handedness
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


def main() -> None:
    summary = parse_summary()
    extractor = WristExtractor()

    swings_to_check = [
        ("swing_09", "normal (mild cupping baseline)"),
        ("swing_15", "normal (clean strike baseline)"),
        ("swing_16", "fault: cupped_lead_wrist_at_top"),
        ("swing_17", "fault: bowed_lead_wrist_at_top"),
        ("swing_18", "fault: scoop_at_impact"),
        ("swing_19", "fault: hold_off_bowed_at_impact"),
    ]

    print(f"{'swing':<12} {'lbl':<38} {'feature':<32} {'value':>10}")
    print("-" * 100)

    for swing_id, label in swings_to_check:
        if swing_id not in summary:
            print(f"({swing_id} not in summary; skipping)")
            continue
        pose_path = POSE_DIR / f"{swing_id}_pose.npz"
        if not pose_path.exists():
            print(f"({pose_path} not found; skipping)")
            continue

        pose = load_pose(pose_path)
        features = extractor.extract(
            pose.landmarks, summary[swing_id], Handedness.RIGHT_HANDED,
        )

        for feature_name, value in features.items():
            val_str = f"{value:>10.2f}" if math.isfinite(value) else f"{'NaN':>10}"
            print(f"{swing_id:<12} {label:<38} {feature_name:<32} {val_str}")
        print()

    # ----- Structural checks -----
    print("--- structural checks ---")

    # 1. Extractor returns exactly the expected keys.
    pose = load_pose(POSE_DIR / "swing_15_pose.npz")
    features = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED,
    )
    expected_keys = set(WristExtractor.FEATURES)
    actual_keys = set(features.keys())
    assert expected_keys == actual_keys, (
        f"Key mismatch: missing={expected_keys - actual_keys}, "
        f"extra={actual_keys - expected_keys}"
    )
    print("OK: extractor produces exactly the expected six keys.")

    # 2. NaN propagates cleanly if a checkpoint frame is NaN-filled.
    poisoned = pose.landmarks.copy()
    p4_frame = summary["swing_15"]["P4"]
    poisoned[p4_frame, :, :] = np.nan
    features_poisoned = extractor.extract(
        poisoned, summary["swing_15"], Handedness.RIGHT_HANDED,
    )
    assert math.isnan(features_poisoned["lead_wrist_angle_at_P4"])
    assert math.isnan(features_poisoned["trail_wrist_angle_at_P4"])
    # But other checkpoints are unaffected.
    assert math.isfinite(features_poisoned["lead_wrist_angle_at_P1"])
    assert math.isfinite(features_poisoned["trail_wrist_angle_at_P7"])
    print("OK: NaN at one checkpoint frame produces NaN there without affecting others.")

    # 3. Left-handed golfer swaps the sides.
    features_rh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED,
    )
    features_lh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.LEFT_HANDED,
    )
    assert features_rh["lead_wrist_angle_at_P4"] == features_lh["trail_wrist_angle_at_P4"]
    assert features_rh["trail_wrist_angle_at_P4"] == features_lh["lead_wrist_angle_at_P4"]
    print("OK: switching handedness swaps lead/trail values as expected.")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()