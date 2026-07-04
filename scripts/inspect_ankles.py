"""Diagnose stance/reference-length options for rotation normalization."""

from __future__ import annotations

import re
import statistics
from pathlib import Path

import numpy as np

from golf_diagnostic.features.landmarks import Handedness, lead, trail
from golf_diagnostic.features.primitives import distance
from golf_diagnostic.pose.extractor import load_pose


REPO_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = REPO_ROOT / "data" / "processed" / "segmentation_summary.txt"
POSE_DIR = REPO_ROOT / "data" / "processed"


def parse_summary():
    out = {}
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


def report(swing_id: str, summary):
    if swing_id not in summary:
        return None
    pose_path = POSE_DIR / f"{swing_id}_pose.npz"
    if not pose_path.exists():
        return None
    pose = load_pose(pose_path)
    p1 = summary[swing_id]["P1"]

    hd = Handedness.RIGHT_HANDED
    lead_ankle = pose.landmarks[p1, lead("ankle", hd)]
    trail_ankle = pose.landmarks[p1, trail("ankle", hd)]
    lead_hip = pose.landmarks[p1, lead("hip", hd)]
    trail_hip = pose.landmarks[p1, trail("hip", hd)]
    lead_shoulder = pose.landmarks[p1, lead("shoulder", hd)]
    trail_shoulder = pose.landmarks[p1, trail("shoulder", hd)]

    hip_midpoint_y = (lead_hip[1] + trail_hip[1]) / 2.0
    ankle_midpoint_y = (lead_ankle[1] + trail_ankle[1]) / 2.0
    shoulder_midpoint_y = (lead_shoulder[1] + trail_shoulder[1]) / 2.0

    return {
        "swing_id": swing_id,
        "ankle_stance_horiz": distance(lead_ankle, trail_ankle),
        "hip_stance_horiz": distance(lead_hip, trail_hip),
        "shoulder_stance_horiz": distance(lead_shoulder, trail_shoulder),
        "ankle_to_hip_vert": abs(ankle_midpoint_y - hip_midpoint_y),
        "hip_to_shoulder_vert": abs(hip_midpoint_y - shoulder_midpoint_y),
        "ankle_to_shoulder_vert": abs(ankle_midpoint_y - shoulder_midpoint_y),
    }


def main():
    summary = parse_summary()
    swings = [f"swing_{i:02d}" for i in range(1, 16)] + ["swing_20", "swing_21", "swing_25"]

    rows = []
    for sid in swings:
        r = report(sid, summary)
        if r:
            rows.append(r)

    keys = [
        "ankle_stance_horiz",
        "hip_stance_horiz",
        "shoulder_stance_horiz",
        "ankle_to_hip_vert",
        "hip_to_shoulder_vert",
        "ankle_to_shoulder_vert",
    ]

    print(f"{'swing':<10} " + " ".join(f"{k:>22}" for k in keys))
    print("-" * (10 + 23 * len(keys)))
    for r in rows:
        line = f"{r['swing_id']:<10} " + " ".join(
            f"{r[k]:>22.4f}" if r[k] is not None else f"{'-':>22}" for k in keys
        )
        print(line)

    print("\n--- distribution across normal swings 1-15 ---")
    normal_rows = [r for r in rows if r["swing_id"] in {f"swing_{i:02d}" for i in range(1, 16)}]
    print(f"{'reference':<24} {'mean':>10} {'stddev':>10} {'coef_var':>10} {'min':>10} {'max':>10}")
    print("-" * 80)
    for k in keys:
        vals = [r[k] for r in normal_rows if r[k] is not None]
        if len(vals) < 2:
            continue
        m = statistics.fmean(vals)
        s = statistics.stdev(vals)
        cv = s / m if m > 0 else float("nan")
        print(f"{k:<24} {m:>10.4f} {s:>10.4f} {cv:>10.2%} {min(vals):>10.4f} {max(vals):>10.4f}")


if __name__ == "__main__":
    main()