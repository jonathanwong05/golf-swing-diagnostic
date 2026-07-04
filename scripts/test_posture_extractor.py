"""
Sanity check for PostureExtractor.

Runs the extractor over normal swings and fault demos where posture
is likely to show a signal:
  swing_23 (early_extension): spine_angle_change_P1_to_P7 should be
                              clearly negative (spine straightened up)
  Normal swings: spine roughly consistent P1 -> P7 (delta near zero),
                 both knees flexed (values ~140-170°), arm relatively
                 straight at P4/P7

Also confirms handedness swap flips lead-arm features to use the
other side.
"""

from __future__ import annotations

import math
import re
import statistics
from pathlib import Path

from golf_diagnostic.features.extractors.posture import PostureExtractor
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
    extractor = PostureExtractor()

    swings = [f"swing_{i:02d}" for i in range(1, 16)] + [
        "swing_20", "swing_21", "swing_23", "swing_25",
    ]
    labels = {
        "swing_20": "fault: over_the_top",
        "swing_21": "fault: stuck_inside",
        "swing_23": "fault: early_extension",
        "swing_25": "fault: short_backswing",
    }

    all_features: dict[str, dict[str, float]] = {}
    for sid in swings:
        if sid not in summary:
            continue
        pose_path = POSE_DIR / f"{sid}_pose.npz"
        if not pose_path.exists():
            continue
        pose = load_pose(pose_path)
        features = extractor.extract(
            pose.landmarks, summary[sid], Handedness.RIGHT_HANDED,
        )
        all_features[sid] = features

    print(f"{'swing':<12} {'label':<28} {'feature':<34} {'value':>10}")
    print("-" * 92)
    for sid in swings:
        if sid not in all_features:
            continue
        label = labels.get(sid, "normal")
        for feature_name, value in all_features[sid].items():
            v = f"{value:>10.2f}" if math.isfinite(value) else f"{'NaN':>10}"
            print(f"{sid:<12} {label:<28} {feature_name:<34} {v}")
        print()

    # Distribution across normal swings.
    print("=" * 60)
    print("Distribution across normal swings 1-15:")
    print("=" * 60)
    normal_ids = [f"swing_{i:02d}" for i in range(1, 16)]
    print(f"{'feature':<34} {'n':>3} {'mean':>8} {'stddev':>8} {'min':>8} {'max':>8}")
    print("-" * 77)
    for feature_name in PostureExtractor.FEATURES:
        vals = [
            all_features[sid][feature_name]
            for sid in normal_ids
            if sid in all_features and math.isfinite(all_features[sid][feature_name])
        ]
        if len(vals) < 2:
            continue
        m = statistics.fmean(vals)
        s = statistics.stdev(vals)
        print(f"{feature_name:<34} {len(vals):>3d} "
              f"{m:>8.2f} {s:>8.2f} {min(vals):>8.2f} {max(vals):>8.2f}")

    # Z-scores for fault demos.
    print("\nFault-demo z-scores against normal distribution:")
    print(f"{'swing':<12} {'feature':<34} {'value':>8} {'z-score':>10}")
    print("-" * 72)
    fault_ids = ["swing_20", "swing_21", "swing_23", "swing_25"]
    for sid in fault_ids:
        if sid not in all_features:
            continue
        for feature_name in PostureExtractor.FEATURES:
            value = all_features[sid][feature_name]
            if not math.isfinite(value):
                continue
            normal_vals = [
                all_features[nsid][feature_name]
                for nsid in normal_ids
                if nsid in all_features
                and math.isfinite(all_features[nsid][feature_name])
            ]
            if len(normal_vals) < 2:
                continue
            m = statistics.fmean(normal_vals)
            s = statistics.stdev(normal_vals)
            z = (value - m) / s if s > 0 else float("nan")
            marker = "  <-- outlier" if abs(z) > 1.5 else ""
            print(f"{sid:<12} {feature_name:<34} {value:>8.2f} {z:>+10.2f}{marker}")

    # Structural checks.
    print("\n--- structural checks ---")
    pose = load_pose(POSE_DIR / "swing_15_pose.npz")
    features = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED,
    )
    assert set(features.keys()) == set(PostureExtractor.FEATURES)
    print(f"OK: extractor produces exactly the expected {len(PostureExtractor.FEATURES)} keys.")

    # Handedness swap: knee_flex_lead should become knee_flex_trail
    # (values swap between the two features when handedness flips).
    features_rh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED,
    )
    features_lh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.LEFT_HANDED,
    )
    assert math.isclose(
        features_rh["knee_flex_lead_at_P1"],
        features_lh["knee_flex_trail_at_P1"],
        abs_tol=1e-9,
    )
    assert math.isclose(
        features_rh["knee_flex_trail_at_P1"],
        features_lh["knee_flex_lead_at_P1"],
        abs_tol=1e-9,
    )
    print("OK: handedness swap swaps lead/trail knee flex values.")

    # Spine angle and its deltas are handedness-independent
    # (they use midpoints of paired landmarks).
    assert math.isclose(
        features_rh["spine_angle_at_P1"],
        features_lh["spine_angle_at_P1"],
        abs_tol=1e-9,
    )
    assert math.isclose(
        features_rh["spine_angle_change_P1_to_P4"],
        features_lh["spine_angle_change_P1_to_P4"],
        abs_tol=1e-9,
    )
    assert math.isclose(
        features_rh["spine_angle_change_P1_to_P7"],
        features_lh["spine_angle_change_P1_to_P7"],
        abs_tol=1e-9,
    )
    print("OK: spine angle and its deltas are handedness-invariant.")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()