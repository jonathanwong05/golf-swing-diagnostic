"""
Sanity check for InterpolatedP5Extractor.

Expected patterns on the normal-swing baseline:
  - lead_wrist_angle_at_P5_proxy: still cupped (positive), since
    release hasn't happened at mid-downswing. Roughly between P4
    and P7 wrist values but weighted toward P4 due to lag.
  - trail_wrist_angle_at_P5_proxy: same story, higher visibility.
  - lead_arm_to_torso_angle_at_P5_proxy: interior angle should be
    smallish (arm relatively connected) — order 30-60 degrees.
  - hand_path_proxy_at_P5_proxy: near zero or slightly positive on
    a well-connected swing; strongly positive on over-the-top
    demos.

No casting demos in the current dataset; casting validation
deferred. Over-the-top (swing_20) is the closest thing — expect
hand_path to show outward drift there.
"""

from __future__ import annotations

import math
import re
import statistics
from pathlib import Path

from golf_diagnostic.features.extractors.interpolated_p5 import (
    InterpolatedP5Extractor,
)
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
            sid, p1, p4, p7, p10 = m.groups()
            out[sid] = {"P1": int(p1), "P4": int(p4), "P7": int(p7), "P10": int(p10)}
    return out


def main() -> None:
    summary = parse_summary()
    extractor = InterpolatedP5Extractor()

    swings = [
        ("swing_01", "normal"),
        ("swing_02", "normal"),
        ("swing_03", "normal"),
        ("swing_04", "normal"),
        ("swing_05", "normal"),
        ("swing_06", "normal"),
        ("swing_07", "normal"),
        ("swing_08", "normal"),
        ("swing_09", "normal (cupping)"),
        ("swing_10", "normal"),
        ("swing_11", "normal"),
        ("swing_12", "normal"),
        ("swing_13", "normal"),
        ("swing_14", "normal"),
        ("swing_15", "normal (clean)"),
        ("swing_16", "fault: cupped_at_top"),
        ("swing_17", "fault: bowed_at_top"),
        ("swing_20", "fault: over_the_top"),
        ("swing_21", "fault: stuck_inside"),
        ("swing_25", "fault: short_backswing"),
    ]

    print(f"{'swing':<12} {'label':<38} {'P4':>4} {'P5':>4} {'P7':>4} "
          f"{'feature':<40} {'value':>10}")
    print("-" * 118)
    for sid, label in swings:
        if sid not in summary:
            continue
        pose_path = POSE_DIR / f"{sid}_pose.npz"
        if not pose_path.exists():
            continue
        pose = load_pose(pose_path)
        cps = summary[sid]
        p5 = round((cps["P4"] + cps["P7"]) / 2)
        features = extractor.extract(
            pose.landmarks, cps, Handedness.RIGHT_HANDED,
        )
        for name, value in features.items():
            v = f"{value:>10.2f}" if math.isfinite(value) else f"{'NaN':>10}"
            print(f"{sid:<12} {label:<38} {cps['P4']:>4} {p5:>4} {cps['P7']:>4} "
                  f"{name:<40} {v}")
        print()

    # Distribution across normal swings.
    print("\n" + "=" * 60)
    print("Distribution across normal swings:")
    print("=" * 60)

    normal_swings = [sid for sid, lbl in swings if lbl.startswith("normal")]
    normal_values: dict[str, list[float]] = {f: [] for f in InterpolatedP5Extractor.FEATURES}

    for sid in normal_swings:
        if sid not in summary:
            continue
        pose_path = POSE_DIR / f"{sid}_pose.npz"
        if not pose_path.exists():
            continue
        pose = load_pose(pose_path)
        features = extractor.extract(
            pose.landmarks, summary[sid], Handedness.RIGHT_HANDED,
        )
        for name, value in features.items():
            if math.isfinite(value):
                normal_values[name].append(value)

    print(f"{'feature':<40} {'n':>3} {'mean':>8} {'stddev':>8} "
          f"{'min':>8} {'max':>8}")
    print("-" * 77)
    for feature_name in InterpolatedP5Extractor.FEATURES:
        vals = normal_values[feature_name]
        if len(vals) < 2:
            continue
        m = statistics.fmean(vals)
        s = statistics.stdev(vals)
        print(f"{feature_name:<40} {len(vals):>3d} "
              f"{m:>8.2f} {s:>8.2f} {min(vals):>8.2f} {max(vals):>8.2f}")

    # Fault-demo z-scores.
    print("\nFault-demo values with z-scores against normal distribution:")
    print(f"{'swing':<12} {'feature':<40} {'value':>8} {'z-score':>10}")
    print("-" * 74)
    for sid, label in swings:
        if not label.startswith("fault"):
            continue
        if sid not in summary:
            continue
        pose_path = POSE_DIR / f"{sid}_pose.npz"
        if not pose_path.exists():
            continue
        pose = load_pose(pose_path)
        features = extractor.extract(
            pose.landmarks, summary[sid], Handedness.RIGHT_HANDED,
        )
        for feature_name, value in features.items():
            vals = normal_values[feature_name]
            if len(vals) < 2 or not math.isfinite(value):
                continue
            m = statistics.fmean(vals)
            s = statistics.stdev(vals)
            z = (value - m) / s if s > 0 else float("nan")
            marker = "  <-- outlier" if abs(z) > 1.5 else ""
            print(f"{sid:<12} {feature_name:<40} "
                  f"{value:>8.2f} {z:>+10.2f}{marker}")

    # Structural checks.
    print("\n--- structural checks ---")

    pose = load_pose(POSE_DIR / "swing_15_pose.npz")
    features = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED,
    )
    assert set(features.keys()) == set(InterpolatedP5Extractor.FEATURES), (
        f"expected {set(InterpolatedP5Extractor.FEATURES)}, got {set(features.keys())}"
    )
    print("OK: extractor produces exactly the expected four keys.")

    # Handedness swap: wrist and lead_arm_to_torso angles should be
    # roughly mirrored. Wrist angles change sign under lead/trail swap
    # only if the anatomical convention flips, which it does here
    # (lead becomes trail and vice versa). We don't assert numeric
    # relationships since the geometry is complex; we just check
    # finite outputs.
    features_lh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.LEFT_HANDED,
    )
    for key in InterpolatedP5Extractor.FEATURES:
        assert math.isfinite(features_lh[key]), (
            f"LH swap produced NaN for {key}"
        )
    print("OK: handedness swap produces finite values for all features.")

    # Degenerate segmentation: p7 <= p4 should return all NaN.
    bad_cps = {"P1": 10, "P4": 40, "P7": 40, "P10": 60}
    degen = extractor.extract(
        pose.landmarks, bad_cps, Handedness.RIGHT_HANDED,
    )
    for key, value in degen.items():
        assert math.isnan(value), f"expected NaN for {key} on degenerate input"
    print("OK: degenerate segmentation (P7 <= P4) returns NaN for all features.")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()