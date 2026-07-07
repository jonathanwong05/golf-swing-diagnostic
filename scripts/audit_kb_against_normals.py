"""
Audit KB thresholds against the normal-swing baseline.

For each loaded symptom, evaluate every normal swing individually
against the KB and check whether the fallback would trigger.
A normal swing that produces a non-fallback ranking is a false
positive — a symptom the tool would diagnose on someone who
didn't demonstrate the fault. Surfaces threshold-tuning problems
before they hit real users.

Usage:
    python scripts/audit_kb_against_normals.py
    python scripts/audit_kb_against_normals.py --symptom slice
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from golf_diagnostic.diagnosis.matcher import (
    match_symptom,
    should_fall_back,
)
from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.features.orchestrator import compute_swing_features
from golf_diagnostic.features.schema import SwingFeatures, aggregate
from golf_diagnostic.kb.loader import load_kb
from golf_diagnostic.pose.extractor import load_pose


REPO_ROOT = Path(__file__).resolve().parent.parent
POSE_DIR = REPO_ROOT / "data" / "processed"
SEG_SUMMARY_PATH = POSE_DIR / "segmentation_summary.txt"
LABELS_PATH = REPO_ROOT / "data" / "labels.yaml"
KB_DIR = REPO_ROOT / "kb"

CHECKPOINT_RE = re.compile(
    r"(swing_\d+).*?P1=\s*(\d+).*?P4=\s*(\d+).*?P7=\s*(\d+).*?P10=\s*(\d+)"
)


def load_checkpoints() -> dict[str, dict[str, int]]:
    text = SEG_SUMMARY_PATH.read_text()
    out: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        m = CHECKPOINT_RE.search(line)
        if not m:
            continue
        sid, p1, p4, p7, p10 = m.groups()
        out[sid] = {"P1": int(p1), "P4": int(p4), "P7": int(p7), "P10": int(p10)}
    return out


def load_normal_swing_ids() -> list[str]:
    with LABELS_PATH.open() as f:
        labels = yaml.safe_load(f)
    return sorted(sid for sid, meta in labels.items() if meta.get("type") == "normal")


def compute_features_for(swing_id: str, checkpoints) -> SwingFeatures:
    pose = load_pose(POSE_DIR / f"{swing_id}_pose.npz")
    return compute_swing_features(
        pose, checkpoints[swing_id], Handedness.RIGHT_HANDED
    )


def audit_symptom(
    symptom: str,
    normal_features: dict[str, SwingFeatures],
    kb,
) -> None:
    print(f"\n=== {symptom} ===")

    false_positives = []            # (swing_id, top_ranked_cause)
    near_misses = []                # (swing_id, top_ranked_cause) where score > 0 but fallback

    for sid, feat in normal_features.items():
        swings = [feat]
        agg = aggregate(swings)
        ranked = match_symptom(symptom, swings, agg, kb)
        if not ranked:
            print(f"  (no causes loaded for {symptom})")
            return
        top = ranked[0]
        if not should_fall_back(ranked):
            false_positives.append((sid, top))
        elif top.score > 0:
            near_misses.append((sid, top))

    n = len(normal_features)
    print(f"  False positives (fallback did NOT trigger): {len(false_positives)}/{n}")
    for sid, top in false_positives:
        print(f"    * {sid}: {top.cause.cause_id} score={top.score:.2f}")
        for mi in top.matched_indicators:
            ind = mi.indicator
            print(
                f"        - {ind.feature} "
                f"[{ind.mode} {ind.operator} {ind.threshold}] "
                f"value={mi.representative_value:.3f} "
                f"weight={ind.confidence_weight}"
            )

    print(f"  Near misses (fallback triggered but score > 0): {len(near_misses)}/{n}")
    for sid, top in near_misses:
        matched = ",".join(mi.indicator.feature for mi in top.matched_indicators)
        print(
            f"    - {sid}: {top.cause.cause_id} score={top.score:.2f} "
            f"[{matched}]"
        )

    if not false_positives and not near_misses:
        print("  All 15 normals clean. No thresholds firing.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symptom",
        default=None,
        help="Audit only this symptom (default: all loaded symptoms)",
    )
    args = parser.parse_args()

    kb = load_kb(KB_DIR)
    loaded = kb.loaded_symptoms()
    if not loaded:
        print("No symptom KBs loaded. Nothing to audit.")
        return

    if args.symptom:
        if args.symptom not in loaded:
            print(
                f"Symptom {args.symptom!r} not loaded. "
                f"Available: {loaded}"
            )
            return
        symptoms_to_audit = [args.symptom]
    else:
        symptoms_to_audit = loaded

    checkpoints = load_checkpoints()
    normal_ids = load_normal_swing_ids()
    print(f"Auditing {len(symptoms_to_audit)} symptom(s) against "
          f"{len(normal_ids)} normal swings.")

    normal_features = {
        sid: compute_features_for(sid, checkpoints) for sid in normal_ids
    }

    for symptom in symptoms_to_audit:
        audit_symptom(symptom, normal_features, kb)


if __name__ == "__main__":
    main()