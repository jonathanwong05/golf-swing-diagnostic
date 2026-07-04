"""
Sanity check for RotationExtractor.

Runs the extractor over baselines and rotation-relevant fault demos.
Expected patterns:

  swing_25 (short backswing):    shoulder/hip proxies at P4 much
                                 closer to zero than baselines
  swing_20 (over-the-top):       shoulder proxy at P7 unusually
                                 open-side (large positive)
  swing_21 (stuck inside):       hip proxy at P7 unusually open
  Normal swings 09, 15:          proxies at P4 clearly negative
                                 (rotated backswing direction) and
                                 proxies at P7 return toward +1
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from golf_diagnostic.features.extractors.rotation import RotationExtractor
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
    extractor = RotationExtractor()

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
            ("swing_20", "fault: over_the_top"),
            ("swing_21", "fault: stuck_inside"),
            ("swing_25", "fault: short_backswing"),
        ]

    print(f"{'swing':<12} {'label':<38} {'feature':<38} {'value':>10}")
    print("-" * 105)
    for sid, label in swings:
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
            v = f"{value:>10.2f}" if math.isfinite(value) else f"{'NaN':>10}"
            print(f"{sid:<12} {label:<38} {feature_name:<38} {v}")
        print()

    # Summary: distribution across normal swings.
    print("\n" + "=" * 60)
    print("Distribution of rotation features across normal swings:")
    print("=" * 60)

    normal_swings = [sid for sid, lbl in swings if lbl.startswith("normal")]
    normal_values: dict[str, list[float]] = {f: [] for f in RotationExtractor.FEATURES}

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

    import statistics
    print(f"{'feature':<38} {'n':>3} {'mean':>8} {'stddev':>8} {'min':>8} {'max':>8}")
    print("-" * 75)
    for feature_name in RotationExtractor.FEATURES:
        vals = normal_values[feature_name]
        if len(vals) < 2:
            continue
        m = statistics.fmean(vals)
        s = statistics.stdev(vals)
        print(f"{feature_name:<38} {len(vals):>3d} "
              f"{m:>8.2f} {s:>8.2f} {min(vals):>8.2f} {max(vals):>8.2f}")

    # Where do the faults land relative to normal?
    print("\nFault-demo values with z-scores against normal distribution:")
    print(f"{'swing':<12} {'feature':<38} {'value':>8} {'z-score':>10}")
    print("-" * 75)
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
            print(f"{sid:<12} {feature_name:<38} "
                  f"{value:>8.2f} {z:>+10.2f}{marker}")

    # Structural checks.
    print("--- structural checks ---")

    pose = load_pose(POSE_DIR / "swing_15_pose.npz")
    features = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED,
    )
    assert set(features.keys()) == set(RotationExtractor.FEATURES)
    print("OK: extractor produces exactly the expected six keys.")

    # Handedness swap: swapping lead/trail flips the sign of separation,
    # which flips the sign of every rotation proxy.
    features_rh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED,
    )
    features_lh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.LEFT_HANDED,
    )
    for key in RotationExtractor.FEATURES:
        rh = features_rh[key]
        lh = features_lh[key]
        if math.isfinite(rh) and math.isfinite(lh):
            # The ratio is normalized by |baseline|, so lead/trail swap
            # flips the sign of the separation but not the denominator.
            # Expected relationship: lh_value == -rh_value.
            assert math.isclose(lh, -rh, abs_tol=1e-9), (
                f"handedness swap should negate {key}: rh={rh}, lh={lh}"
            )
    print("OK: handedness swap flips the sign of all rotation proxies.")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()