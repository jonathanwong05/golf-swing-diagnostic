"""
End-to-end sanity check for the feature orchestrator.

Runs `compute_swing_features` on every available swing and confirms:
  - Every field in the returned SwingFeatures is populated (finite
    or NaN, never missing).
  - No extractor raises unexpectedly.
  - The per-extractor outputs, computed standalone, match the fields
    in the merged SwingFeatures.
  - Invalid checkpoints raise ValueError.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from golf_diagnostic.features.extractors.interpolated_p5 import (
    InterpolatedP5Extractor,
)
from golf_diagnostic.features.extractors.position import PositionExtractor
from golf_diagnostic.features.extractors.posture import PostureExtractor
from golf_diagnostic.features.extractors.rotation import RotationExtractor
from golf_diagnostic.features.extractors.tempo import TempoExtractor
from golf_diagnostic.features.extractors.wrists import WristExtractor
from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.features.orchestrator import compute_swing_features
from golf_diagnostic.features.schema import FEATURE_NAMES
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
    print(f"Found {len(summary)} swings in segmentation summary.\n")

    # ------------------------------------------------------------------
    # Run orchestrator on every available swing.
    # ------------------------------------------------------------------

    all_features: dict[str, dict[str, float]] = {}
    nan_counts_per_feature: dict[str, int] = {name: 0 for name in FEATURE_NAMES}

    for sid, cps in sorted(summary.items()):
        pose_path = POSE_DIR / f"{sid}_pose.npz"
        if not pose_path.exists():
            continue
        pose = load_pose(pose_path)

        features = compute_swing_features(pose, cps, Handedness.RIGHT_HANDED)
        features_dict = features.to_dict()

        # Confirm no missing fields.
        assert set(features_dict.keys()) == set(FEATURE_NAMES), (
            f"{sid} produced feature names {sorted(features_dict.keys())} "
            f"but schema expects {sorted(FEATURE_NAMES)}"
        )

        all_features[sid] = features_dict
        for name, value in features_dict.items():
            if not math.isfinite(value):
                nan_counts_per_feature[name] += 1

    n = len(all_features)
    print(f"OK: orchestrator ran on {n} swings, all {len(FEATURE_NAMES)} "
          f"schema fields populated on each.\n")

    # ------------------------------------------------------------------
    # NaN summary across the dataset.
    # ------------------------------------------------------------------

    print("=" * 60)
    print(f"NaN counts per feature across {n} swings:")
    print("=" * 60)
    any_nans = False
    for name in FEATURE_NAMES:
        count = nan_counts_per_feature[name]
        if count > 0:
            any_nans = True
            print(f"  {name:<44} {count}/{n} NaN")
    if not any_nans:
        print("  (none — every feature is finite on every swing)")

    # ------------------------------------------------------------------
    # Cross-check: merged orchestrator output == per-extractor outputs.
    # Verifies the orchestrator isn't silently transforming values.
    # ------------------------------------------------------------------

    print("\n" + "=" * 60)
    print("Cross-check against standalone extractor calls (swing_15):")
    print("=" * 60)

    pose = load_pose(POSE_DIR / "swing_15_pose.npz")
    cps = summary["swing_15"]

    orch = compute_swing_features(pose, cps, Handedness.RIGHT_HANDED).to_dict()

    standalone: dict[str, float] = {}
    for extractor, extra_kwargs in [
        (WristExtractor(),          {}),
        (RotationExtractor(),       {}),
        (PostureExtractor(),        {}),
        (PositionExtractor(),       {}),
        (TempoExtractor(),          {"fps": pose.fps}),
        (InterpolatedP5Extractor(), {}),
    ]:
        result = extractor.extract(
            pose.landmarks, cps, Handedness.RIGHT_HANDED, **extra_kwargs,
        )
        for key, value in result.items():
            assert key not in standalone, f"duplicate producer for {key}"
            standalone[key] = value

    mismatches = []
    for name in FEATURE_NAMES:
        a = orch[name]
        b = standalone[name]
        if math.isnan(a) and math.isnan(b):
            continue
        if a != b:
            mismatches.append((name, a, b))

    if mismatches:
        print("MISMATCH:")
        for name, a, b in mismatches:
            print(f"  {name}: orchestrator={a}, standalone={b}")
        raise AssertionError("orchestrator diverges from standalone extractors")
    print("OK: every feature matches standalone-extractor output.")

    # ------------------------------------------------------------------
    # Invalid-input checks.
    # ------------------------------------------------------------------

    print("\n--- structural checks ---")

    # Missing keys.
    try:
        compute_swing_features(pose, {"P1": 10, "P4": 20}, Handedness.RIGHT_HANDED)
    except ValueError as e:
        print(f"OK: missing checkpoints raises ValueError -> {e}")
    else:
        raise AssertionError("expected ValueError on missing checkpoints")

    # Bad ordering.
    try:
        compute_swing_features(
            pose,
            {"P1": 50, "P4": 20, "P7": 30, "P10": 40},
            Handedness.RIGHT_HANDED,
        )
    except ValueError as e:
        print(f"OK: bad ordering raises ValueError -> {e}")
    else:
        raise AssertionError("expected ValueError on bad ordering")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()