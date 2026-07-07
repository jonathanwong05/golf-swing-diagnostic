"""
End-to-end sanity check for the KB matcher on slice.yaml.

Test A: 3 normal swings vs symptom=slice. Expect fallback to trigger
        (no fault demoed, so causes should not fire strongly).

Test B: swing_16 (cupped_lead_wrist_at_top demo) as a single "upload"
        vs symptom=slice. Expect the cupped-wrist cause to rank #1
        with score >= 1.0.
"""

from __future__ import annotations

import re
from pathlib import Path

from golf_diagnostic import kb
from golf_diagnostic.diagnosis.matcher import (
    match_symptom,
    should_fall_back,
)
from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.features.orchestrator import compute_swing_features
from golf_diagnostic.features.schema import aggregate
from golf_diagnostic.kb.loader import load_kb
from golf_diagnostic.pose.extractor import load_pose


REPO_ROOT = Path(__file__).resolve().parent.parent
POSE_DIR = REPO_ROOT / "data" / "processed"
SEG_SUMMARY_PATH = POSE_DIR / "segmentation_summary.txt"
KB_DIR = REPO_ROOT / "kb"

CHECKPOINT_RE = re.compile(
    r"(swing_\d+).*?P1=\s*(\d+).*?P4=\s*(\d+).*?P7=\s*(\d+).*?P10=\s*(\d+)"
)


def load_checkpoints() -> dict[str, dict[str, int]]:
    text = SEG_SUMMARY_PATH.read_text()
    out = {}
    for line in text.splitlines():
        m = CHECKPOINT_RE.search(line)
        if not m:
            continue
        sid, p1, p4, p7, p10 = m.groups()
        out[sid] = {"P1": int(p1), "P4": int(p4), "P7": int(p7), "P10": int(p10)}
    return out


def features_for(swing_ids, checkpoints):
    features = []
    for sid in swing_ids:
        pose = load_pose(POSE_DIR / f"{sid}_pose.npz")
        features.append(
            compute_swing_features(pose, checkpoints[sid], Handedness.RIGHT_HANDED)
        )
    return features


def print_ranking(label, ranked):
    print(f"\n=== {label} ===")
    if should_fall_back(ranked):
        print("  FALLBACK TRIGGERED (no clear cause detected)")
    for r in ranked:
        marker = "*" if r.matched_indicators else " "
        print(f"  {marker} {r.cause.cause_id}: score={r.score:.2f}")
        for mi in r.matched_indicators:
            ind = mi.indicator
            print(
                f"      - {ind.feature} "
                f"[{ind.mode} {ind.operator} {ind.threshold}] "
                f"hits={mi.hit_count}/{mi.swing_count} "
                f"value={mi.representative_value:.3f} "
                f"weight={ind.confidence_weight}"
            )


def main() -> None:
    checkpoints = load_checkpoints()
    kb = load_kb(KB_DIR)

    # Test A: 3 normal swings
    normal_ids = ["swing_09", "swing_12", "swing_15"]
    normal_features = features_for(normal_ids, checkpoints)
    ranked_a = match_symptom("slice", normal_features, aggregate(normal_features), kb)
    print_ranking(f"Test A: 3 normal swings ({', '.join(normal_ids)}) vs slice", ranked_a)

    # Test B: swing_16 (cupped fault demo) alone
    demo_features = features_for(["swing_16"], checkpoints)
    ranked_b = match_symptom("slice", demo_features, aggregate(demo_features), kb)
    print_ranking("Test B: swing_16 (cupped_lead_wrist_at_top demo) vs slice", ranked_b)

    # Test C: swing_25 (short_backswing demo) vs lack_of_distance
    demo_features_c = features_for(["swing_25"], checkpoints)
    ranked_c = match_symptom("lack_of_distance", demo_features_c, aggregate(demo_features_c), kb)
    print_ranking("Test C: swing_25 (short_backswing demo) vs lack_of_distance", ranked_c)

    # Test D: swing_22 (hanging_back demo) vs push
    demo_features_d = features_for(["swing_22"], checkpoints)
    ranked_d = match_symptom("push", demo_features_d, aggregate(demo_features_d), kb)
    print_ranking("Test D: swing_22 (hanging_back demo) vs push", ranked_d)

    # Test E: All 15 normal swings grouped vs inconsistent_contact
    normal_ids = [f"swing_{i:02d}" for i in range(1, 16)]
    all_normals = features_for(normal_ids, checkpoints)
    ranked_e = match_symptom("inconsistent_contact", all_normals, aggregate(all_normals), kb)
    print_ranking(f"Test E: 15 normals grouped ({len(normal_ids)} swings) vs inconsistent_contact", ranked_e)

    # Test F: Highly variable set — mix of fault demos vs inconsistent_contact
    mixed_ids = ["swing_16", "swing_17", "swing_20", "swing_22", "swing_25"]
    mixed = features_for(mixed_ids, checkpoints)
    ranked_f = match_symptom("inconsistent_contact", mixed, aggregate(mixed), kb)
    print_ranking(f"Test F: 5 different fault demos ({','.join(mixed_ids)}) vs inconsistent_contact", ranked_f)


if __name__ == "__main__":
    main()