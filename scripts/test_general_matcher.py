"""Sanity script for match_general (Phase 5.1).

Tests the matcher-side additions without hitting the Anthropic API.
Prompt / LLM integration is validated separately.

Checks:

1. **Dedup mechanics.** Count total cause entries across all symptom
   files vs. unique cause_ids after dedup. Confirms shared causes
   exist and dedup is doing real work. Also implicitly verifies
   ``_assert_causes_identical`` passes on the current KB — a
   consistency-rule violation would raise here.

2. **Fallback on normal swings.** ``match_general`` on 3 normal
   swings from the baseline dataset should fall back. If a normal
   swing gets diagnosed under general mode, thresholds are too
   loose.

3. **Score parity: swing_16 vs slice.** cupped_lead_wrist_at_top
   only appears in slice.yaml, so its general-mode score must
   exactly match its slice-mode score (identical _score_cause
   call on identical Cause object).

4. **Score parity: swing_25 vs lack_of_distance.** Same test on
   a different cause / demo pair. insufficient_body_rotation lives
   only in lack_of_distance.yaml.

5. **Consistency-check probe.** Dump the top 10 causes by score
   from swing_16 to eyeball the ranking. Not an assertion — a
   visual sanity check that ranked general output is coherent.

Run from project root::

    python scripts/test_general_matcher.py

Requires cached pose NPZs in ``data/processed/`` and
``segmentation_summary.txt`` (both produced by
``scripts/batch_segment.py``).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from golf_diagnostic.diagnosis.matcher import (
    FALLBACK_SCORE_FLOOR,
    RankedCause,
    match_general,
    match_symptom,
    should_fall_back,
)
from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.features.orchestrator import compute_swing_features
from golf_diagnostic.features.schema import aggregate
from golf_diagnostic.kb.loader import KnowledgeBase, load_kb
from golf_diagnostic.pose.extractor import load_pose

REPO_ROOT = Path(__file__).resolve().parent.parent
POSE_DIR = REPO_ROOT / "data" / "processed"
KB_DIR = REPO_ROOT / "kb"
SEG_SUMMARY = POSE_DIR / "segmentation_summary.txt"

CHECKPOINT_PATTERN = re.compile(
    r"(swing_\d+).*?P1=\s*(\d+).*?P4=\s*(\d+).*?P7=\s*(\d+).*?P10=\s*(\d+)"
)


# --------------------------------------------------------------------------
# Fixture loading (same regex pattern as prior sanity scripts)
# --------------------------------------------------------------------------

def _load_checkpoints(swing_ids: set[str]) -> dict[str, dict[str, int]]:
    """Parse checkpoints from segmentation_summary.txt for the given IDs."""
    if not SEG_SUMMARY.is_file():
        raise FileNotFoundError(
            f"{SEG_SUMMARY} not found — run scripts/batch_segment.py first."
        )
    checkpoints: dict[str, dict[str, int]] = {}
    with SEG_SUMMARY.open() as f:
        for line in f:
            m = CHECKPOINT_PATTERN.search(line)
            if not m:
                continue
            sid = m.group(1)
            if sid in swing_ids:
                checkpoints[sid] = {
                    "P1": int(m.group(2)),
                    "P4": int(m.group(3)),
                    "P7": int(m.group(4)),
                    "P10": int(m.group(5)),
                }
    missing = swing_ids - checkpoints.keys()
    if missing:
        raise RuntimeError(
            f"Missing checkpoints for swings: {sorted(missing)}"
        )
    return checkpoints


def _compute_features_for(swing_ids: list[str]):
    """Load pose + compute features for each swing; return list + aggregate."""
    ckpts = _load_checkpoints(set(swing_ids))
    features = []
    for sid in swing_ids:
        pose = load_pose(POSE_DIR / f"{sid}_pose.npz")
        feat = compute_swing_features(pose, ckpts[sid], Handedness.RIGHT_HANDED)
        features.append(feat)
    return features, aggregate(features)


def _find_ranked(ranked: list[RankedCause], cause_id: str) -> RankedCause | None:
    for r in ranked:
        if r.cause.cause_id == cause_id:
            return r
    return None


# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------

def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}", file=sys.stderr)
    sys.exit(1)


def _check(cond: bool, msg: str) -> None:
    (_ok if cond else _fail)(msg)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_dedup_mechanics(kb: KnowledgeBase) -> None:
    print("\n[1] Dedup mechanics")

    total_entries = sum(
        len(kb.get_causes(s)) for s in kb.loaded_symptoms()
    )
    print(f"  Total cause entries across symptoms: {total_entries}")

    # Call match_general to trigger dedup. Assertion inside
    # _assert_causes_identical will raise if the KB has divergent
    # entries for a shared cause_id.
    features, agg = _compute_features_for(["swing_16"])
    ranked = match_general(features, agg, kb)
    unique_count = len(ranked)
    print(f"  Unique cause_ids after dedup:        {unique_count}")

    _check(unique_count > 0, "at least one unique cause after dedup")
    _check(
        unique_count < total_entries,
        f"dedup reduced count ({total_entries} → {unique_count}); shared causes exist",
    )
    # Gut-level sanity: order-of-magnitude check that dedup didn't
    # produce something absurd. Range is generous — the KB's actual
    # unique count depends on how sharing plays out across symptom
    # files.
    _check(
        20 <= unique_count <= 30,
        f"unique count in expected 20-30 range (got {unique_count})",
    )


def test_normal_swings_fallback(kb: KnowledgeBase) -> None:
    print("\n[2] General mode on 3 normal swings → fallback")

    features, agg = _compute_features_for(["swing_01", "swing_02", "swing_03"])
    ranked = match_general(features, agg, kb)

    top = ranked[0] if ranked else None
    top_id = top.cause.cause_id if top else "(none)"
    top_score = top.score if top else 0.0
    print(f"  top: {top_id} @ {top_score:.2f}")

    _check(should_fall_back(ranked), "should_fall_back returns True")
    _check(
        top_score < FALLBACK_SCORE_FLOOR,
        f"top score < {FALLBACK_SCORE_FLOOR} (got {top_score:.2f})",
    )


def test_swing_16_score_parity(kb: KnowledgeBase) -> None:
    print("\n[3] Score parity: swing_16 in general vs slice mode")

    features, agg = _compute_features_for(["swing_16"])
    general = match_general(features, agg, kb)
    slice_ranked = match_symptom("slice", features, agg, kb)

    g_cupped = _find_ranked(general, "cupped_lead_wrist_at_top")
    s_cupped = _find_ranked(slice_ranked, "cupped_lead_wrist_at_top")

    _check(g_cupped is not None, "cupped_lead_wrist_at_top in general ranking")
    _check(s_cupped is not None, "cupped_lead_wrist_at_top in slice ranking")
    if g_cupped is None or s_cupped is None:
        return  # already failed via _check

    print(f"  general score: {g_cupped.score:.4f}")
    print(f"  slice   score: {s_cupped.score:.4f}")

    _check(
        g_cupped.score == s_cupped.score,
        f"scores identical (general={g_cupped.score:.4f}, slice={s_cupped.score:.4f})",
    )
    _check(
        general[0].cause.cause_id == "cupped_lead_wrist_at_top",
        f"cupped_lead_wrist_at_top is #1 in general ranking "
        f"(got {general[0].cause.cause_id})",
    )
    _check(
        g_cupped.score >= FALLBACK_SCORE_FLOOR,
        f"top general score clears floor (got {g_cupped.score:.2f})",
    )


def test_swing_25_score_parity(kb: KnowledgeBase) -> None:
    print("\n[4] Score parity: swing_25 in general vs lack_of_distance mode")

    features, agg = _compute_features_for(["swing_25"])
    general = match_general(features, agg, kb)
    lod_ranked = match_symptom("lack_of_distance", features, agg, kb)

    g_ibr = _find_ranked(general, "insufficient_body_rotation")
    l_ibr = _find_ranked(lod_ranked, "insufficient_body_rotation")

    _check(g_ibr is not None, "insufficient_body_rotation in general ranking")
    _check(l_ibr is not None, "insufficient_body_rotation in lack_of_distance ranking")
    if g_ibr is None or l_ibr is None:
        return

    print(f"  general           score: {g_ibr.score:.4f}")
    print(f"  lack_of_distance  score: {l_ibr.score:.4f}")

    _check(
        g_ibr.score == l_ibr.score,
        "scores identical between general and lack_of_distance mode",
    )
    _check(
        g_ibr.score >= FALLBACK_SCORE_FLOOR,
        f"score clears floor (got {g_ibr.score:.2f})",
    )


def print_top_ranking_probe(kb: KnowledgeBase) -> None:
    print("\n[5] Visual probe: top 10 ranked causes for swing_16 general mode")

    features, agg = _compute_features_for(["swing_16"])
    ranked = match_general(features, agg, kb)

    print(f"  (of {len(ranked)} total unique causes)")
    for r in ranked[:10]:
        n_matched = len(r.matched_indicators)
        marker = "  " if r.score < FALLBACK_SCORE_FLOOR else "*"
        print(
            f"  {marker} {r.score:5.2f}  [{n_matched} matched]  "
            f"{r.cause.cause_id}"
        )
    print("  (* = clears fallback floor)")


def test_feels_pooling(kb: KnowledgeBase) -> None:
    """Verify shared causes carry the pooled coaching vocabulary in general mode.

    Uses early_extension as the probe cause (appears in 6 symptom
    files per Phase 3 notes, so the pooled feels list should be
    larger than any single symptom's feels list).
    """
    print("\n[6] Coaching pool: shared cause has pooled feels/drills in general mode")

    features, agg = _compute_features_for(["swing_16"])
    general = match_general(features, agg, kb)

    # early_extension appears in 6 symptom files; general mode should
    # union their feels. Compare against slice's per-symptom version.
    g_ee = _find_ranked(general, "early_extension")
    _check(g_ee is not None, "early_extension in general ranking")
    if g_ee is None:
        return

    # Pick any symptom containing early_extension for the comparison.
    # Slice contains it per phase3 notes.
    slice_ranked = match_symptom("slice", features, agg, kb)
    s_ee = _find_ranked(slice_ranked, "early_extension")
    _check(s_ee is not None, "early_extension in slice ranking")
    if s_ee is None:
        return

    n_pooled = len(g_ee.cause.feels)
    n_slice = len(s_ee.cause.feels)
    n_pooled_drills = len(g_ee.cause.drills)
    n_slice_drills = len(s_ee.cause.drills)

    print(f"  early_extension feels:  general={n_pooled}, slice={n_slice}")
    print(f"  early_extension drills: general={n_pooled_drills}, slice={n_slice_drills}")

    _check(
        n_pooled >= n_slice,
        f"pooled feels count >= single-symptom count "
        f"({n_pooled} >= {n_slice})",
    )
    _check(
        n_pooled_drills >= n_slice_drills,
        f"pooled drills count >= single-symptom count "
        f"({n_pooled_drills} >= {n_slice_drills})",
    )

    # Every slice feel should also appear in the pooled list (union
    # preserves everything).
    slice_feel_texts = {f.feel for f in s_ee.cause.feels}
    pooled_feel_texts = {f.feel for f in g_ee.cause.feels}
    _check(
        slice_feel_texts.issubset(pooled_feel_texts),
        "every slice feel appears in the pooled feels (union preserves all)",
    )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    print(f"Loading KB from {KB_DIR}")
    kb = load_kb(KB_DIR)
    print(f"Loaded {len(kb.loaded_symptoms())} symptoms")

    test_dedup_mechanics(kb)
    test_normal_swings_fallback(kb)
    test_swing_16_score_parity(kb)
    test_swing_25_score_parity(kb)
    print_top_ranking_probe(kb)
    test_feels_pooling(kb)

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()