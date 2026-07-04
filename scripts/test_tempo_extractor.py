"""
Sanity check for TempoExtractor.

Expected patterns:
  - Normal swings: tempo_ratio in the 2.0-4.0 range, total duration
    around 1.0-1.5 seconds (varies with individual tempo)
  - Any tempo_ratio outside [1.5, 5.0] on a normal swing suggests a
    P4 segmentation issue on that swing (not a tempo-extractor bug)
  - Any total_swing_duration above 2.5s suggests P10 fell back to
    last-frame on a clip that never settled to finish
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from golf_diagnostic.features.extractors.tempo import TempoExtractor
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
    extractor = TempoExtractor()

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

    print(f"{'swing':<12} {'label':<38} {'fps':>6} "
          f"{'P1':>4} {'P4':>4} {'P7':>4} {'P10':>4} "
          f"{'tempo_ratio':>12} {'duration_s':>12}")
    print("-" * 108)

    for sid, label in swings:
        if sid not in summary:
            continue
        pose_path = POSE_DIR / f"{sid}_pose.npz"
        if not pose_path.exists():
            continue
        pose = load_pose(pose_path)
        features = extractor.extract(
            pose.landmarks, summary[sid], Handedness.RIGHT_HANDED, fps=pose.fps,
        )
        cps = summary[sid]
        tr = features["tempo_ratio"]
        dur = features["total_swing_duration"]
        tr_s = f"{tr:>12.2f}" if math.isfinite(tr) else f"{'NaN':>12}"
        dur_s = f"{dur:>12.2f}" if math.isfinite(dur) else f"{'NaN':>12}"
        print(f"{sid:<12} {label:<38} {pose.fps:>6.1f} "
              f"{cps['P1']:>4} {cps['P4']:>4} {cps['P7']:>4} {cps['P10']:>4} "
              f"{tr_s} {dur_s}")

    # Distribution across normal swings.
    print("\n" + "=" * 60)
    print("Distribution across normal swings:")
    print("=" * 60)

    normal_swings = [sid for sid, lbl in swings if lbl.startswith("normal")]
    normal_values: dict[str, list[float]] = {f: [] for f in TempoExtractor.FEATURES}

    for sid in normal_swings:
        if sid not in summary:
            continue
        pose_path = POSE_DIR / f"{sid}_pose.npz"
        if not pose_path.exists():
            continue
        pose = load_pose(pose_path)
        features = extractor.extract(
            pose.landmarks, summary[sid], Handedness.RIGHT_HANDED, fps=pose.fps,
        )
        for name, value in features.items():
            if math.isfinite(value):
                normal_values[name].append(value)

    import statistics
    print(f"{'feature':<26} {'n':>3} {'mean':>8} {'stddev':>8} "
          f"{'min':>8} {'max':>8}")
    print("-" * 63)
    for feature_name in TempoExtractor.FEATURES:
        vals = normal_values[feature_name]
        if len(vals) < 2:
            continue
        m = statistics.fmean(vals)
        s = statistics.stdev(vals)
        print(f"{feature_name:<26} {len(vals):>3d} "
              f"{m:>8.2f} {s:>8.2f} {min(vals):>8.2f} {max(vals):>8.2f}")

    # Fault-demo z-scores.
    print("\nFault-demo values with z-scores against normal distribution:")
    print(f"{'swing':<12} {'feature':<26} {'value':>8} {'z-score':>10}")
    print("-" * 60)
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
            pose.landmarks, summary[sid], Handedness.RIGHT_HANDED, fps=pose.fps,
        )
        for feature_name, value in features.items():
            vals = normal_values[feature_name]
            if len(vals) < 2 or not math.isfinite(value):
                continue
            m = statistics.fmean(vals)
            s = statistics.stdev(vals)
            z = (value - m) / s if s > 0 else float("nan")
            marker = "  <-- outlier" if abs(z) > 1.5 else ""
            print(f"{sid:<12} {feature_name:<26} "
                  f"{value:>8.2f} {z:>+10.2f}{marker}")

    # Structural checks.
    print("\n--- structural checks ---")

    pose = load_pose(POSE_DIR / "swing_15_pose.npz")
    features = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED, fps=pose.fps,
    )
    assert set(features.keys()) == set(TempoExtractor.FEATURES)
    print("OK: extractor produces exactly the expected two keys.")

    # Handedness swap should not change tempo (no landmarks).
    features_rh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED, fps=pose.fps,
    )
    features_lh = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.LEFT_HANDED, fps=pose.fps,
    )
    for key in TempoExtractor.FEATURES:
        assert features_rh[key] == features_lh[key], (
            f"handedness should not affect {key}: rh={features_rh[key]}, "
            f"lh={features_lh[key]}"
        )
    print("OK: handedness swap does not change tempo features.")

    # fps=None should produce NaN duration but still compute tempo_ratio.
    features_no_fps = extractor.extract(
        pose.landmarks, summary["swing_15"], Handedness.RIGHT_HANDED, fps=None,
    )
    assert math.isfinite(features_no_fps["tempo_ratio"]), (
        "tempo_ratio should be finite when fps=None"
    )
    assert math.isnan(features_no_fps["total_swing_duration"]), (
        "total_swing_duration should be NaN when fps=None"
    )
    print("OK: fps=None produces NaN duration but valid tempo_ratio.")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()