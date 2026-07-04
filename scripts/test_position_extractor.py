"""
Sanity check for the position extractor.

Runs the extractor over all swings in labels.yaml, prints baseline
distributions across normal swings, and flags fault-demo z-scores
against that baseline for the features each fault should move.
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

import numpy as np
import yaml

from golf_diagnostic.features.extractors.position import PositionExtractor
from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.pose.extractor import load_pose


REPO_ROOT = Path(__file__).resolve().parent.parent
POSE_DIR = REPO_ROOT / "data" / "processed"
SUMMARY_PATH = POSE_DIR / "segmentation_summary.txt"
LABELS_PATH = REPO_ROOT / "data" / "labels.yaml"


FAULT_EXPECTATIONS: dict[str, list[tuple[str, int]]] = {
    "reverse_pivot": [
        ("head_displacement_P1_to_P4", +1),
    ],
    "early_extension": [
        ("hip_vertical_change_P1_to_P7", +1),
        ("head_vertical_change_P1_to_P7", +1),
    ],
    "hanging_back": [
        ("head_displacement_P1_to_P7_target_axis", -1),
    ],
    "standing_too_close": [
        ("hand_distance_from_body_at_P1", -1),
    ],
}


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
    with open(LABELS_PATH) as f:
        labels = yaml.safe_load(f)

    summary = parse_summary()
    extractor = PositionExtractor()
    results: dict[str, dict[str, float]] = {}

    for swing_id, meta in labels.items():
        if swing_id not in summary:
            print(f"({swing_id} not in segmentation summary; skipping)")
            continue
        pose_path = POSE_DIR / f"{swing_id}_pose.npz"
        if not pose_path.exists():
            print(f"({pose_path} not found; skipping)")
            continue
        pose = load_pose(pose_path)
        results[swing_id] = extractor.extract(
            pose.landmarks, summary[swing_id], Handedness.RIGHT_HANDED,
        )

    normal_ids = [
        sid for sid, meta in labels.items()
        if meta.get("type") == "normal" and sid in results
    ]

    print("=" * 78)
    print(f"Normal swing distributions (n={len(normal_ids)})")
    print("=" * 78)
    baselines: dict[str, tuple[float, float]] = {}
    for feat in PositionExtractor.FEATURES:
        vals = [
            results[sid][feat]
            for sid in normal_ids
            if np.isfinite(results[sid][feat])
        ]
        if len(vals) < 2:
            print(f"  {feat:52s}  insufficient data (n={len(vals)})")
            baselines[feat] = (float("nan"), float("nan"))
            continue
        m = statistics.fmean(vals)
        s = statistics.stdev(vals)
        cv = abs(s / m) if abs(m) > 1e-6 else float("inf")
        baselines[feat] = (m, s)
        print(f"  {feat:52s}  mean={m:+.4f}  sd={s:.4f}  cv={cv:.2f}  n={len(vals)}")

    print()
    print("=" * 78)
    print("Fault demo z-scores against normal baseline")
    print("=" * 78)
    for swing_id, meta in labels.items():
        if meta.get("type") != "fault_demo" or swing_id not in results:
            continue
        fault = meta.get("intended_fault", "unknown")
        expected = FAULT_EXPECTATIONS.get(fault, [])
        print(f"\n{swing_id} — intended fault: {fault}")
        if not expected:
            print("  (no position-extractor expectations for this fault)")
            continue
        for feat, expected_sign in expected:
            val = results[swing_id][feat]
            m, s = baselines[feat]
            if not (np.isfinite(val) and np.isfinite(m) and s > 1e-8):
                print(f"  {feat:50s}  value={val}  (baseline unavailable)")
                continue
            z = (val - m) / s
            sign_ok = (expected_sign > 0 and z > 0) or (expected_sign < 0 and z < 0)
            flag = "OK " if sign_ok and abs(z) >= 1.0 else "?? "
            print(
                f"  {flag}{feat:48s}  value={val:+.4f}  z={z:+.2f}  "
                f"(expected sign {expected_sign:+d})"
            )

    print()
    print("=" * 78)
    print("NaN counts across all swings")
    print("=" * 78)
    for feat in PositionExtractor.FEATURES:
        n = sum(1 for sid in results if not np.isfinite(results[sid][feat]))
        status = "OK" if n == 0 else f"WARN ({n} NaN)"
        print(f"  {feat:52s}  {status}")

    print()
    print("=" * 78)
    print("All position-extractor values for fault demos (reference)")
    print("=" * 78)
    for swing_id, meta in labels.items():
        if meta.get("type") != "fault_demo" or swing_id not in results:
            continue
        fault = meta.get("intended_fault", "unknown")
        print(f"\n{swing_id} — {fault}")
        for feat in PositionExtractor.FEATURES:
            v = results[swing_id][feat]
            v_str = f"{v:+.4f}" if np.isfinite(v) else "NaN"
            print(f"  {feat:52s}  {v_str}")


if __name__ == "__main__":
    main()