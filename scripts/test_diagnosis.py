"""
Spike test for the diagnostic LLM layer.

Actually calls the Anthropic API. Two cases:
  A. diagnosis mode with cupped_lead_wrist_at_top at score 1.40
     (validated demo). Expects a primary CauseExplanation citing
     the cupped cause.
  B. fallback mode with all sub-floor scores. Expects a
     fallback_message that references what came close and any
     invisible-axis blind spots.

Uses manually-constructed RankedCause fixtures — no pose pipeline
needed. Same pattern as test_prompt.py.

Estimated cost per full run: ~$0.03 with prompt caching.

Requires ANTHROPIC_API_KEY in the environment.

Run from repo root:
    python scripts/test_diagnosis.py
"""

from pathlib import Path

from golf_diagnostic.diagnosis.llm_client import generate_diagnosis
from golf_diagnostic.diagnosis.matcher import MatchedIndicator, RankedCause
from golf_diagnostic.diagnosis.output_schema import DiagnosticOutput
from golf_diagnostic.kb.loader import Cause, KnowledgeBase, load_kb


BAR = "=" * 78


# ---------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------


def _fake_hit(
    cause: Cause,
    indicator_index: int,
    value: float,
    hit_count: int = 4,
    swing_count: int = 4,
) -> MatchedIndicator:
    return MatchedIndicator(
        indicator=cause.indicators[indicator_index],
        hit_count=hit_count,
        swing_count=swing_count,
        representative_value=value,
    )


def _find(causes: list[Cause], cause_id: str) -> Cause:
    for c in causes:
        if c.cause_id == cause_id:
            return c
    raise KeyError(f"cause_id {cause_id!r} not in provided list")


def _build_diagnosis_ranked(kb: KnowledgeBase) -> list[RankedCause]:
    """Mixed scores, top cause validated (cupped)."""
    slice_causes = kb.get_causes("slice")
    cupped = _find(slice_causes, "cupped_lead_wrist_at_top")

    primary = RankedCause(
        cause=cupped,
        score=1.40,
        matched_indicators=[
            _fake_hit(cupped, 0, value=52.1),
            *(
                [_fake_hit(cupped, 1, value=41.7)]
                if len(cupped.indicators) > 1
                else []
            ),
        ],
    )

    remaining = [c for c in slice_causes if c.cause_id != cupped.cause_id]
    ranked = [primary]
    scores = [0.90, 0.50, 0.30]
    for cause, score in zip(remaining, scores):
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


def _build_fallback_ranked(kb: KnowledgeBase) -> list[RankedCause]:
    """All causes below the diagnostic floor."""
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
# Rendering
# ---------------------------------------------------------------------


def _print_output(
    output: DiagnosticOutput,
    ranked: list[RankedCause],
    kb: KnowledgeBase,
    symptom: str,
) -> None:
    """Render a DiagnosticOutput with feels/drills resolved from the KB."""
    print()
    print(f"summary:\n  {output.summary}")

    if output.primary is not None:
        _print_explanation("PRIMARY", output.primary, kb, symptom)

    for i, sec in enumerate(output.secondary):
        _print_explanation(f"SECONDARY[{i}]", sec, kb, symptom)

    if output.fallback_message is not None:
        print()
        print("fallback_message:")
        print(f"  {output.fallback_message}")


def _print_explanation(
    label: str,
    exp,
    kb: KnowledgeBase,
    symptom: str,
) -> None:
    print()
    print(f"{label}:")
    print(f"  cause_id: {exp.cause_id}")

    # Resolve feel_id and drill_ids back to KB content
    cause = _find(kb.get_causes(symptom), exp.cause_id)
    feel = cause.feels[exp.feel_id]

    print(f"  technical_explanation:\n    {exp.technical_explanation}")
    print(f"  bridge_to_feel:\n    {exp.bridge_to_feel}")
    print(f"  selected feel (feel_id={exp.feel_id}):")
    print(f"    \"{feel.feel}\"")
    if feel.best_for:
        print(f"    best_for: {feel.best_for}")

    if exp.drill_ids:
        print(f"  drills (drill_ids={exp.drill_ids}):")
        for did in exp.drill_ids:
            print(f"    - {cause.drills[did].name}")
    else:
        print(f"  drills: (none selected)")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main() -> None:
    print("Loading KB…")
    kb = load_kb(Path("kb"))
    if not kb.get_causes("slice"):
        print("  slice.yaml not loaded; cannot run.")
        return
    print(f"  Loaded {len(kb.get_causes('slice'))} slice causes.")

    # ---- Case A: diagnosis --------------------------------------
    print()
    print(BAR)
    print("  CASE A — diagnosis mode (cupped_lead_wrist_at_top, score 1.40)")
    print(BAR)

    ranked_a = _build_diagnosis_ranked(kb)
    print("\nInput ranked list:")
    for rc in ranked_a:
        print(f"  - {rc.cause.cause_id}: {rc.score:.2f}")

    output_a = generate_diagnosis(
        symptom="slice",
        ranked=ranked_a,
        kb=kb,
        n_swings=4,
        user_context=(
            "I've been slicing for years. My coach mentioned early "
            "extension a while back but I couldn't feel it."
        ),
        verbose=True,
    )

    print("\n--- LLM output ---")
    _print_output(output_a, ranked_a, kb, "slice")

    # Sanity assertions
    assert output_a.primary is not None, "diagnosis mode should populate primary"
    assert output_a.fallback_message is None, "diagnosis mode should not populate fallback_message"
    print("\n  [PASS] Case A: primary populated, fallback_message null")

    if output_a.primary.cause_id == "cupped_lead_wrist_at_top":
        print("  [PASS] Case A: primary is cupped_lead_wrist_at_top (highest-scored cause)")
    else:
        print(
            f"  [INFO] Case A: primary is {output_a.primary.cause_id!r} "
            f"instead of cupped_lead_wrist_at_top; LLM chose differently. "
            f"Not a bug — worth eyeballing whether the reasoning is sound."
        )

    # ---- Case B: fallback ---------------------------------------
    print()
    print(BAR)
    print("  CASE B — fallback mode (all sub-floor scores)")
    print(BAR)

    ranked_b = _build_fallback_ranked(kb)
    print("\nInput ranked list (all sub-floor):")
    for rc in ranked_b:
        print(f"  - {rc.cause.cause_id}: {rc.score:.2f}")

    output_b = generate_diagnosis(
        symptom="slice",
        ranked=ranked_b,
        kb=kb,
        n_swings=3,
        user_context="",
        verbose=True,
    )

    print("\n--- LLM output ---")
    _print_output(output_b, ranked_b, kb, "slice")

    assert output_b.primary is None, "fallback should not populate primary"
    assert output_b.fallback_message is not None, "fallback should populate fallback_message"
    assert not output_b.secondary, "fallback should have empty secondary"
    print("\n  [PASS] Case B: fallback_message populated, primary/secondary empty")

    # Weak check: fallback message should ideally mention at least one
    # invisible-axis feature. Case-insensitive keyword match.
    msg_lower = output_b.fallback_message.lower()
    invisible_axis_keywords = ["grip", "alignment", "weight", "face-on", "face on"]
    hits = [k for k in invisible_axis_keywords if k in msg_lower]
    if hits:
        print(f"  [PASS] Case B: fallback references invisible-axis topics: {hits}")
    else:
        print(
            f"  [INFO] Case B: fallback_message did not mention any of "
            f"{invisible_axis_keywords} — worth eyeballing whether the "
            f"LLM offered useful next steps."
        )

    print("\nDone.")


if __name__ == "__main__":
    main()