"""
End-to-end feature validation against labels.yaml.

For each fault_demo swing in the dataset, this script:
  1. Runs the orchestrator to get its SwingFeatures.
  2. Compares each expected feature against the normal-swing baseline.
  3. Reports PASS / WEAK / FAIL / NaN per (swing, feature) pair.

Baseline is the set of swings labeled `type: normal`. Baseline
mean/stddev per feature is computed once and re-used across all
fault demos.

Pass criteria per feature:
  PASS: finite value, sign matches expected direction, |z| >= 1.0
  WEAK: finite value, sign matches expected direction, |z| <  1.0
  FAIL: finite value, sign wrong (regardless of magnitude)
  NaN : value is not finite

Exit code:
  0 if no unexpected FAILs. A FAIL on a feature marked `known_weak`
    is reported but does not fail the run.
  1 if any un-marked feature FAILs.

Deferred demos (`deferred: true` in labels.yaml) are skipped.
"""

from __future__ import annotations

import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.features.orchestrator import compute_swing_features
from golf_diagnostic.features.schema import FEATURE_NAMES
from golf_diagnostic.pose.extractor import load_pose


REPO_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = REPO_ROOT / "data" / "processed" / "segmentation_summary.txt"
POSE_DIR = REPO_ROOT / "data" / "processed"
LABELS_PATH = REPO_ROOT / "data" / "labels.yaml"

Z_THRESHOLD = 1.0

# Result codes.
PASS = "PASS"
WEAK = "WEAK"
FAIL = "FAIL"
NAN = "NaN "  # padded for column alignment


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


def load_labels() -> dict[str, dict]:
    with open(LABELS_PATH) as f:
        return yaml.safe_load(f)


def compute_features_for_swing(sid: str, checkpoints: dict[str, int]) -> dict[str, float] | None:
    """Run orchestrator on one swing; return feature dict or None if pose is missing."""
    pose_path = POSE_DIR / f"{sid}_pose.npz"
    if not pose_path.exists():
        return None
    pose = load_pose(pose_path)
    features = compute_swing_features(pose, checkpoints, Handedness.RIGHT_HANDED)
    return features.to_dict()


def classify_result(
    value: float,
    direction: str,
    baseline_mean: float,
    baseline_stddev: float,
) -> tuple[str, float]:
    """
    Return (result_code, z_score).

    z_score is computed as (value - mean) / stddev. If stddev is 0 or
    NaN, z_score is NaN and result is FAIL (can't check direction).
    """
    if not math.isfinite(value):
        return NAN, float("nan")
    if baseline_stddev <= 0 or not math.isfinite(baseline_stddev):
        return FAIL, float("nan")

    z = (value - baseline_mean) / baseline_stddev
    if direction == "high":
        if z >= Z_THRESHOLD:
            return PASS, z
        elif z > 0:
            return WEAK, z
        else:
            return FAIL, z
    elif direction == "low":
        if z <= -Z_THRESHOLD:
            return PASS, z
        elif z < 0:
            return WEAK, z
        else:
            return FAIL, z
    else:
        raise ValueError(f"unknown direction: {direction!r}")


def main() -> int:
    labels = load_labels()
    summary = parse_summary()

    # ------------------------------------------------------------------
    # Build normal-swing baseline (mean, stddev per feature).
    # ------------------------------------------------------------------

    normal_ids = [sid for sid, meta in labels.items() if meta.get("type") == "normal"]
    fault_ids = [
        sid for sid, meta in labels.items() if meta.get("type") == "fault_demo"
    ]

    baseline_values: dict[str, list[float]] = {name: [] for name in FEATURE_NAMES}
    n_normal_used = 0
    for sid in normal_ids:
        if sid not in summary:
            continue
        features = compute_features_for_swing(sid, summary[sid])
        if features is None:
            continue
        n_normal_used += 1
        for name, value in features.items():
            if math.isfinite(value):
                baseline_values[name].append(value)

    baseline: dict[str, tuple[float, float]] = {}
    for name in FEATURE_NAMES:
        vals = baseline_values[name]
        if len(vals) >= 2:
            baseline[name] = (statistics.fmean(vals), statistics.stdev(vals))
        else:
            baseline[name] = (float("nan"), float("nan"))

    print("=" * 74)
    print(f"Normal baseline: {n_normal_used} normal swings.")
    print("=" * 74)

    # ------------------------------------------------------------------
    # Run each fault demo through the classifier.
    # ------------------------------------------------------------------

    # Aggregate counters.
    counts = {PASS: 0, WEAK: 0, FAIL: 0, NAN: 0}
    counts_known_weak = {PASS: 0, WEAK: 0, FAIL: 0, NAN: 0}
    unexpected_fails: list[tuple[str, str, str, float]] = []  # (sid, fault, feature, z)
    fault_groups: dict[str, list[str]] = defaultdict(list)  # for by-fault summary

    print("\n=== per-demo results ===\n")

    for sid in fault_ids:
        meta = labels[sid]
        fault = meta.get("intended_fault", "?")
        fault_groups[fault].append(sid)

        if meta.get("deferred"):
            print(f"{sid} ({fault}): SKIPPED — deferred to v2")
            print()
            continue

        if sid not in summary:
            print(f"{sid} ({fault}): SKIPPED — no segmentation entry")
            print()
            continue

        features = compute_features_for_swing(sid, summary[sid])
        if features is None:
            print(f"{sid} ({fault}): SKIPPED — no pose data file")
            print()
            continue

        expected = meta.get("expected_features") or {}
        if not expected:
            print(f"{sid} ({fault}): SKIPPED — no expected_features declared")
            print()
            continue

        print(f"{sid} ({fault}):")
        for feature_name, spec in expected.items():
            # spec is a dict with `direction` and optional `known_weak`.
            if not isinstance(spec, dict) or "direction" not in spec:
                print(f"  {feature_name:<44} SKIPPED — malformed spec")
                continue
            direction = spec["direction"]
            known_weak = bool(spec.get("known_weak", False))

            if feature_name not in FEATURE_NAMES:
                print(f"  {feature_name:<44} SKIPPED — unknown feature (not in schema)")
                continue

            value = features[feature_name]
            mean, stddev = baseline[feature_name]
            result, z = classify_result(value, direction, mean, stddev)

            # Bucket into overall counts.
            if known_weak:
                counts_known_weak[result] += 1
            else:
                counts[result] += 1

            marker = " (known_weak)" if known_weak else ""
            value_s = f"{value:>+8.3f}" if math.isfinite(value) else f"{'NaN':>8}"
            z_s = f"{z:>+7.2f}" if math.isfinite(z) else f"{'NaN':>7}"
            print(f"  {feature_name:<44} value={value_s}  z={z_s}  "
                  f"[{result}] dir={direction}{marker}")

            if result == FAIL and not known_weak:
                unexpected_fails.append((sid, fault, feature_name, z))

        print()

    # ------------------------------------------------------------------
    # Summary by fault type.
    # ------------------------------------------------------------------

    print("=" * 74)
    print("=== summary by intended fault ===")
    print("=" * 74)
    for fault, sids in sorted(fault_groups.items()):
        print(f"  {fault:<36} {len(sids)} demo(s): {', '.join(sids)}")

    # ------------------------------------------------------------------
    # Aggregate counts.
    # ------------------------------------------------------------------

    print("\n" + "=" * 74)
    print("=== aggregate results ===")
    print("=" * 74)
    print("Not marked known_weak:")
    for code in (PASS, WEAK, FAIL, NAN):
        print(f"  {code.strip():<6} {counts[code]}")
    print("\nMarked known_weak:")
    for code in (PASS, WEAK, FAIL, NAN):
        print(f"  {code.strip():<6} {counts_known_weak[code]}")

    # ------------------------------------------------------------------
    # Unexpected failures (the ones that fail the run).
    # ------------------------------------------------------------------

    if unexpected_fails:
        print("\n" + "=" * 74)
        print("=== unexpected FAILs (not known_weak) ===")
        print("=" * 74)
        for sid, fault, feature, z in unexpected_fails:
            z_s = f"{z:>+7.2f}" if math.isfinite(z) else "   NaN"
            print(f"  {sid:<10} {fault:<32} {feature:<40} z={z_s}")
        print(f"\n{len(unexpected_fails)} unexpected FAIL(s). Exit code 1.")
        return 1

    print("\nNo unexpected FAILs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())