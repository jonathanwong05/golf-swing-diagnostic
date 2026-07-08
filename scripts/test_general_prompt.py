"""Sanity script for general-mode prompt construction (Phase 5.1).

Does NOT hit the Anthropic API. Builds prompts from real matcher
output (swing_16 for diagnosis, three normal swings for fallback),
prints them for eyeball inspection, and verifies the diagnosis-mode
invariant fires when it should.

Purpose: confirm that
1. ``build_prompt(symptom=None, ...)`` runs end-to-end without error.
2. The user message header renders "Analysis type: general" for
   general mode and "Analysis type: symptom-driven" for symptom mode.
3. The system prompt contains the new sections referenced by
   general mode.
4. The mode invariant (``mode="diagnosis"`` with no above-floor
   cause) still raises ``ValueError`` when ``symptom=None``.
5. The tool schema and cache_control marks are unchanged from
   symptom-mode behavior.

Run from project root::

    python scripts/test_general_prompt.py

Requires cached pose NPZs in ``data/processed/`` and
``segmentation_summary.txt``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from golf_diagnostic.diagnosis.matcher import (
    FALLBACK_SCORE_FLOOR,
    match_general,
    should_fall_back,
)
from golf_diagnostic.diagnosis.prompt import (
    FALLBACK_TOP_N,
    NORMAL_TOP_N,
    build_prompt,
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
# Fixture loading
# --------------------------------------------------------------------------

def _load_checkpoints(swing_ids: set[str]) -> dict[str, dict[str, int]]:
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
        raise RuntimeError(f"Missing checkpoints for: {sorted(missing)}")
    return checkpoints


def _compute_features_for(swing_ids: list[str]):
    ckpts = _load_checkpoints(set(swing_ids))
    features = []
    for sid in swing_ids:
        pose = load_pose(POSE_DIR / f"{sid}_pose.npz")
        feat = compute_swing_features(pose, ckpts[sid], Handedness.RIGHT_HANDED)
        features.append(feat)
    return features, aggregate(features)


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
# System-prompt content assertions
# --------------------------------------------------------------------------

_REQUIRED_SYSTEM_PROMPT_MARKERS = [
    # New Phase 5.1 sections
    "Symptom-driven vs general analysis",
    "General-mode fallback",
    "Symptom-driven fallback",
    # Explicit header strings the LLM keys on
    '"Analysis type: symptom-driven"',
    '"Analysis type: general"',
    # Concrete example anchor
    "no ball-flight assertion",
]


def check_system_prompt_content(payload) -> None:
    system_text = payload.system[0]["text"]
    for marker in _REQUIRED_SYSTEM_PROMPT_MARKERS:
        _check(
            marker in system_text,
            f"system prompt contains {marker!r}",
        )
    _check(
        payload.system[0]["cache_control"] == {"type": "ephemeral"},
        "system block is cache-marked",
    )
    _check(
        payload.tools[0].get("cache_control") == {"type": "ephemeral"},
        "tool schema is cache-marked",
    )
    _check(
        payload.tools[0]["name"] == "emit_diagnosis",
        "tool name is emit_diagnosis",
    )
    _check(
        payload.tool_choice == {"type": "tool", "name": "emit_diagnosis"},
        "tool_choice forces emit_diagnosis",
    )


# --------------------------------------------------------------------------
# Test cases
# --------------------------------------------------------------------------

def case_a_general_diagnosis(kb: KnowledgeBase) -> None:
    print("\n[A] General diagnosis mode — swing_16 (cupped demo)")
    features, agg = _compute_features_for(["swing_16"])
    ranked = match_general(features, agg, kb)
    _check(not should_fall_back(ranked), "swing_16 clears fallback floor")

    payload = build_prompt(
        symptom=None,
        ranked=ranked,
        kb=kb,
        n_swings=1,
        mode="diagnosis",
        user_context="I'm just curious how my swing looks overall.",
    )

    check_system_prompt_content(payload)

    user_msg = payload.messages[0]["content"]

    _check(
        "Analysis type: general" in user_msg,
        "user message header says 'Analysis type: general'",
    )
    _check(
        "no specific symptom reported" in user_msg,
        "user message notes no symptom reported",
    )
    _check(
        "Analysis type: symptom-driven" not in user_msg,
        "user message does NOT claim symptom-driven analysis",
    )
    _check(
        "The user reports:" not in user_msg,
        "user message does NOT report a symptom",
    )
    _check(
        "cupped_lead_wrist_at_top" in user_msg,
        "top-scored cause appears in user message",
    )

    print()
    print("--- user message (general diagnosis) ---")
    print(user_msg)
    print("--- end user message ---")


def case_b_general_fallback(kb: KnowledgeBase) -> None:
    print("\n[B] General fallback mode — 3 normal swings")
    features, agg = _compute_features_for(["swing_01", "swing_02", "swing_03"])
    ranked = match_general(features, agg, kb)
    _check(should_fall_back(ranked), "3 normal swings trigger fallback")

    payload = build_prompt(
        symptom=None,
        ranked=ranked,
        kb=kb,
        n_swings=3,
        mode="fallback",
        user_context="",
    )
    user_msg = payload.messages[0]["content"]

    _check(
        "Analysis type: general" in user_msg,
        "user message header says 'Analysis type: general'",
    )
    _check(
        "No cause cleared" in user_msg,
        "user message notes no cause cleared the threshold",
    )
    _check(
        "fallback response per the fallback-mode rules" in user_msg,
        "user message instructs fallback response",
    )

    # Count how many causes were surfaced. Fallback mode surfaces up
    # to FALLBACK_TOP_N regardless of score.
    n_surfaced = user_msg.count("### Cause ")
    _check(
        1 <= n_surfaced <= FALLBACK_TOP_N,
        f"fallback surfaces 1..{FALLBACK_TOP_N} causes for the LLM to reference "
        f"(got {n_surfaced})",
    )

    print()
    print("--- user message (general fallback, first 100 lines) ---")
    for line in user_msg.splitlines()[:100]:
        print(line)
    print("--- (truncated) ---")


def case_c_general_diagnosis_invariant(kb: KnowledgeBase) -> None:
    print("\n[C] Invariant: diagnosis mode + all sub-floor ranked → ValueError")
    # Use the same 3 normal swings that should fall back
    features, agg = _compute_features_for(["swing_01", "swing_02", "swing_03"])
    ranked = match_general(features, agg, kb)
    _check(
        should_fall_back(ranked),
        "precondition: 3 normal swings do fall back",
    )
    _check(
        all(rc.score < FALLBACK_SCORE_FLOOR for rc in ranked),
        "precondition: no ranked cause clears the floor",
    )

    try:
        build_prompt(
            symptom=None,
            ranked=ranked,
            kb=kb,
            n_swings=3,
            mode="diagnosis",
            user_context="",
        )
    except ValueError as e:
        _ok(f"raised ValueError: {str(e)[:80]}...")
        return
    _fail("build_prompt did not raise ValueError")


def case_d_symptom_mode_still_works(kb: KnowledgeBase) -> None:
    print("\n[D] Regression: symptom-driven mode still renders correctly")
    features, agg = _compute_features_for(["swing_16"])
    # Use match_general so we have the same ranked list; the important
    # thing is that build_prompt accepts a real symptom string and
    # renders the symptom-driven header.
    ranked = match_general(features, agg, kb)

    payload = build_prompt(
        symptom="slice",
        ranked=ranked,
        kb=kb,
        n_swings=1,
        mode="diagnosis",
        user_context="",
    )
    user_msg = payload.messages[0]["content"]

    _check(
        "Analysis type: symptom-driven" in user_msg,
        "user message header says 'Analysis type: symptom-driven'",
    )
    _check(
        "The user reports: **slice**" in user_msg,
        "user message reports the symptom",
    )
    _check(
        "Analysis type: general" not in user_msg,
        "user message does NOT say general",
    )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    print(f"Loading KB from {KB_DIR}")
    kb = load_kb(KB_DIR)
    print(f"Loaded {len(kb.loaded_symptoms())} symptoms")
    print(f"NORMAL_TOP_N={NORMAL_TOP_N}, FALLBACK_TOP_N={FALLBACK_TOP_N}")

    case_a_general_diagnosis(kb)
    case_b_general_fallback(kb)
    case_c_general_diagnosis_invariant(kb)
    case_d_symptom_mode_still_works(kb)

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()