"""
Sanity script for diagnosis/prompt.py.

Does NOT hit the Anthropic API. Builds prompts from manually-
constructed RankedCause fixtures and prints them so we can eyeball
the system prompt, the user message, and the tool schema before
spending tokens on real LLM calls.

Uses real KB data (loads kb/) and real RankedCause / MatchedIndicator
types (imports from matcher) — fixtures fail at import time if
those schemas drift.

Three cases:
  A. Diagnosis mode with mixed scores — verifies top-N filter drops
     sub-floor causes from the surfaced list.
  B. Fallback mode with all sub-floor scores — verifies fallback
     surfaces more causes than diagnosis does.
  C. Same all-sub-floor list but mode="diagnosis" — verifies the
     empty-ranked-list edge case renders sensibly.

Then a tool-schema summary confirms name, cache_control, and top-
level fields.

Run from repo root:
    python scripts/test_prompt.py
"""

from pathlib import Path

from golf_diagnostic.diagnosis.matcher import (
    FALLBACK_SCORE_FLOOR,
    MatchedIndicator,
    RankedCause,
)
from golf_diagnostic.diagnosis.prompt import (
    FALLBACK_TOP_N,
    NORMAL_TOP_N,
    build_prompt,
)
from golf_diagnostic.kb.loader import Cause, load_kb


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


BAR = "=" * 78
SUB = "-" * 78


def _print_header(title: str) -> None:
    print()
    print(BAR)
    print(f"  {title}")
    print(BAR)


def _print_sub(title: str) -> None:
    print()
    print(SUB)
    print(title)
    print(SUB)


def _fake_hit(
    cause: Cause,
    indicator_index: int,
    value: float,
    hit_count: int = 4,
    swing_count: int = 4,
) -> MatchedIndicator:
    """Build a plausible MatchedIndicator from a real KB indicator."""
    return MatchedIndicator(
        indicator=cause.indicators[indicator_index],
        hit_count=hit_count,
        swing_count=swing_count,
        representative_value=value,
    )


def _find(cause_list: list[Cause], cause_id: str) -> Cause:
    for c in cause_list:
        if c.cause_id == cause_id:
            return c
    raise KeyError(f"cause_id {cause_id!r} not found in provided list")


# ---------------------------------------------------------------------
# Fixtures — built from real KB data
# ---------------------------------------------------------------------


def _build_diagnosis_ranked(kb) -> list[RankedCause]:
    """
    Mixed-score ranked list for slice:
    - cupped_lead_wrist_at_top at 1.40 (well above floor) — primary
    - over_the_top-style cause at 0.90 (above floor) — secondary
    - another cause at 0.50 (just at floor) — secondary
    - a cause at 0.30 (below floor) — should be filtered out by
      _select_ranked in diagnosis mode

    Uses whichever real slice causes exist. Adapts if not all four
    causes are present.
    """
    slice_causes = kb.get_causes("slice")
    if len(slice_causes) < 2:
        raise RuntimeError(
            f"slice KB has {len(slice_causes)} causes; need >=2 for this test"
        )

    cupped = _find(slice_causes, "cupped_lead_wrist_at_top")

    # Primary: cupped, strong hit on trail wrist + lead wrist corroborator
    primary = RankedCause(
        cause=cupped,
        score=1.40,
        matched_indicators=[
            _fake_hit(cupped, 0, value=52.1),  # trail_wrist_angle_at_P4
            # Second indicator only if the cause has one, else skip
            *(
                [_fake_hit(cupped, 1, value=41.7)]
                if len(cupped.indicators) > 1
                else []
            ),
        ],
    )

    # Fill in remaining causes with plausible-looking sub-scores
    remaining = [c for c in slice_causes if c.cause_id != cupped.cause_id]
    ranked = [primary]
    fake_scores = [0.90, 0.50, 0.30]
    for cause, score in zip(remaining, fake_scores):
        if not cause.indicators:
            continue
        ranked.append(
            RankedCause(
                cause=cause,
                score=score,
                matched_indicators=[_fake_hit(cause, 0, value=1.85)],
            )
        )

    return ranked


def _build_fallback_ranked(kb) -> list[RankedCause]:
    """
    All-sub-floor ranked list for slice — nothing clears the diagnostic
    floor. Represents the case where the user reported "slice" but no
    cause fires strongly enough to diagnose.
    """
    slice_causes = kb.get_causes("slice")
    scores = [0.40, 0.30, 0.30, 0.20]
    ranked = []
    for cause, score in zip(slice_causes, scores):
        if not cause.indicators:
            continue
        ranked.append(
            RankedCause(
                cause=cause,
                score=score,
                matched_indicators=[_fake_hit(cause, 0, value=1.62)],
            )
        )
    return ranked


# ---------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------


def _print_payload(payload) -> None:
    _print_sub("SYSTEM PROMPT (first block; cacheable)")
    for block in payload.system:
        print(f"  content type: {block['type']}")
        print(f"  cache_control: {block.get('cache_control')}")
        text = block["text"]
        print(f"  text length: {len(text)} chars")
        # Print first 400 chars, then '...', then last 200 chars
        # to keep output scannable but reveal both ends.
        if len(text) > 700:
            print()
            print(text[:400])
            print("...")
            print(text[-200:])
        else:
            print()
            print(text)

    _print_sub("USER MESSAGE (dynamic; NOT cacheable)")
    assert len(payload.messages) == 1
    print(payload.messages[0]["content"])

    _print_sub("TOOL SCHEMA (cacheable)")
    assert len(payload.tools) == 1
    tool = payload.tools[0]
    print(f"  tool name: {tool['name']}")
    print(f"  cache_control: {tool.get('cache_control')}")
    top_level_props = list(
        tool["input_schema"].get("properties", {}).keys()
    )
    print(f"  input_schema top-level properties: {top_level_props}")

    _print_sub("TOOL CHOICE")
    print(f"  {payload.tool_choice}")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main() -> None:
    print(f"NORMAL_TOP_N = {NORMAL_TOP_N}")
    print(f"FALLBACK_TOP_N = {FALLBACK_TOP_N}")
    print(f"FALLBACK_SCORE_FLOOR (from matcher) = {FALLBACK_SCORE_FLOOR}")

    print("\nLoading KB…")
    kb = load_kb(Path("kb"))
    slice_causes = kb.get_causes("slice")
    if not slice_causes:
        print("slice.yaml did not load — cannot run prompt tests.")
        return
    print(f"  Loaded {len(slice_causes)} slice causes.")

    # ---- Case A: diagnosis with mixed scores --------------------
    _print_header("CASE A — diagnosis mode, mixed scores")

    ranked_a = _build_diagnosis_ranked(kb)
    print(f"\nInput ranked list ({len(ranked_a)} causes):")
    for rc in ranked_a:
        marker = "  (above floor)" if rc.score >= FALLBACK_SCORE_FLOOR else "  (below floor — should be dropped)"
        print(f"  - {rc.cause.cause_id}: score {rc.score:.2f}{marker}")

    payload_a = build_prompt(
        symptom="slice",
        ranked=ranked_a,
        kb=kb,
        n_swings=4,
        mode="diagnosis",
        user_context=(
            "I've been slicing for years. My coach mentioned early "
            "extension a while back but I couldn't feel it."
        ),
    )
    _print_payload(payload_a)

    # Assertion: only above-floor causes should appear in the user message
    below_floor_ids = [
        rc.cause.cause_id for rc in ranked_a if rc.score < FALLBACK_SCORE_FLOOR
    ]
    user_msg_a = payload_a.messages[0]["content"]
    for cid in below_floor_ids:
        if cid in user_msg_a:
            print(
                f"\n  [FAIL] sub-floor cause {cid!r} appeared in "
                f"diagnosis-mode user message; expected filtered out."
            )
            return
    print("\n  [PASS] sub-floor causes correctly filtered out in diagnosis mode")

    # ---- Case B: fallback with all sub-floor scores -------------
    _print_header("CASE B — fallback mode, all sub-floor scores")

    ranked_b = _build_fallback_ranked(kb)
    print(f"\nInput ranked list ({len(ranked_b)} causes, all sub-floor):")
    for rc in ranked_b:
        print(f"  - {rc.cause.cause_id}: score {rc.score:.2f}")

    payload_b = build_prompt(
        symptom="slice",
        ranked=ranked_b,
        kb=kb,
        n_swings=3,
        mode="fallback",
        user_context="",
    )
    _print_payload(payload_b)

    # Assertion: fallback should include causes even though sub-floor
    if len(ranked_b) > 0:
        first_id = ranked_b[0].cause.cause_id
        if first_id not in payload_b.messages[0]["content"]:
            print(
                f"\n  [FAIL] highest-scoring sub-floor cause {first_id!r} "
                f"missing from fallback user message; expected included."
            )
            return
    print("\n  [PASS] sub-floor causes included in fallback-mode user message")

    # ---- Case C: same all-sub-floor list, mode="diagnosis" ------
    _print_header("CASE C — sub-floor list in diagnosis mode (invariant fires)")

    print(
        "\nExpectation: build_prompt raises ValueError. "
        "Caller should have detected this via should_fall_back()."
    )
    try:
        build_prompt(
            symptom="slice",
            ranked=ranked_b,  # reuse the sub-floor list
            kb=kb,
            n_swings=3,
            mode="diagnosis",
            user_context="",
        )
    except ValueError as e:
        print(f"\n  [PASS] ValueError raised as expected:")
        print(f"    {e}")
    except Exception as e:
        print(f"\n  [FAIL] expected ValueError, got {type(e).__name__}: {e}")
        return
    else:
        print("\n  [FAIL] expected ValueError, no exception raised")
        return

    # ---- Tool schema summary ------------------------------------
    _print_header("TOOL SCHEMA SUMMARY")
    tool = payload_a.tools[0]
    print(f"  name: {tool['name']}")
    print(f"  description length: {len(tool['description'])} chars")
    print(f"  cache_control: {tool.get('cache_control')}")

    schema = tool["input_schema"]
    top_level = schema.get("properties", {})
    print(f"  top-level required: {schema.get('required', [])}")
    print(f"  top-level properties: {list(top_level.keys())}")

    expected = {"summary", "primary", "secondary", "fallback_message"}
    got = set(top_level.keys())
    missing = expected - got
    extra = got - expected
    if missing:
        print(f"\n  [FAIL] tool schema missing expected top-level fields: {missing}")
        return
    if extra:
        print(f"  [INFO] tool schema has extra top-level fields (may be fine): {extra}")
    print("\n  [PASS] tool schema has expected top-level fields")

    if tool.get("cache_control") != {"type": "ephemeral"}:
        print(f"\n  [FAIL] tool cache_control not set correctly: {tool.get('cache_control')}")
        return
    print("  [PASS] tool cache_control set to ephemeral")

    system_block = payload_a.system[0]
    if system_block.get("cache_control") != {"type": "ephemeral"}:
        print(f"\n  [FAIL] system block cache_control not set: {system_block.get('cache_control')}")
        return
    print("  [PASS] system block cache_control set to ephemeral")

    print("\nDone.")


if __name__ == "__main__":
    main()