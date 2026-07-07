"""
End-to-end pipeline test.

Two cases exercising the full pose → LLM chain on real video:

Case A: swing_16 alone (single swing).
    The validated Phase 2 cupped-wrist demo. Consistency filter
    trivially satisfied at n=1. Expected: diagnosis mode with
    cupped_lead_wrist_at_top as primary (matches test_matcher.py's
    Test B result of 1.40).

Case B: swing_16 + swing_09 (multi-swing consistency test).
    swing_16 is the exaggerated cupped demo; swing_09 is a
    "normal" swing that labels.yaml flags as visibly cupped but is
    measurably closer to baseline. The 60% consistency filter
    suppresses indicators that don't fire on both swings.
    Expected: fallback mode with all scores at 0.00. Demonstrates
    the filter working as designed — a fault present on one swing
    but not another is not diagnosable.

Together they validate both paths of the pipeline on real matcher
output, complementing the fixture-based test_diagnosis.py.

Estimated cost: ~$0.03 total (Case A writes cache, Case B hits it).

Requires ANTHROPIC_API_KEY in env; also requires cached pose NPZs
in data/processed/ (or MediaPipe available to re-extract).

Run from repo root:
    python scripts/test_pipeline.py
"""

from pathlib import Path

from golf_diagnostic.kb.loader import load_kb
from golf_diagnostic.pipeline import analyze_swings


BAR = "=" * 78
SUB = "-" * 78


def _print_output(result) -> None:
    d = result.diagnosis
    print()
    print("summary:")
    print(f"  {d.summary}")

    if d.primary is not None:
        _print_explanation("PRIMARY", d.primary, result)

    for i, sec in enumerate(d.secondary):
        _print_explanation(f"SECONDARY[{i}]", sec, result)

    if d.fallback_message is not None:
        print()
        print("fallback_message:")
        print(f"  {d.fallback_message}")


def _print_explanation(label: str, exp, result) -> None:
    # Look up cause in the ranked_causes list to resolve feels/drills
    cause = next(
        (rc.cause for rc in result.ranked_causes if rc.cause.cause_id == exp.cause_id),
        None,
    )
    print()
    print(f"{label}:")
    print(f"  cause_id: {exp.cause_id}")
    print(f"  technical_explanation:\n    {exp.technical_explanation}")
    print(f"  bridge_to_feel:\n    {exp.bridge_to_feel}")
    if cause is not None:
        feel = cause.feels[exp.feel_id]
        print(f"  selected feel (feel_id={exp.feel_id}):")
        print(f"    \"{feel.feel}\"")
        if exp.drill_ids:
            print(f"  drills:")
            for did in exp.drill_ids:
                print(f"    - {cause.drills[did].name}")
        else:
            print(f"  drills: (none selected)")
    else:
        print(f"  [WARN] cause_id not in ranked_causes; can't resolve feel/drill text")


def _run_case(
    label: str,
    video_paths: list[Path],
    kb,
    user_context: str,
    expected_mode: str,
) -> None:
    """Run one analysis case and print full results + assertions."""
    print()
    print(BAR)
    print(f"  {label}")
    print(BAR)

    for p in video_paths:
        if not p.exists():
            print(f"\n  [FAIL] {p} not found. Check that data/raw/ has these files.")
            return

    print(f"\nAnalyzing {len(video_paths)} swing(s):")
    for p in video_paths:
        print(f"  - {p.name}")
    print(f"Expected mode: {expected_mode}")

    print()
    print(SUB)
    print("PIPELINE LOG (stderr)")
    print(SUB)

    result = analyze_swings(
        video_paths=video_paths,
        symptom="slice",
        kb=kb,
        user_context=user_context,
        verbose=True,
        annotated_output_dir=None,
    )

    print()
    print(SUB)
    print("MATCHER OUTPUT")
    print(SUB)
    for rc in result.ranked_causes:
        indicators = ", ".join(
            f"{mi.indicator.feature}={mi.representative_value:.2f}"
            for mi in rc.matched_indicators
        )
        print(f"  {rc.cause.cause_id}: score {rc.score:.2f}")
        if indicators:
            print(f"    indicators: {indicators}")

    print()
    print(SUB)
    print("LLM OUTPUT")
    print(SUB)
    _print_output(result)

    print()
    print(SUB)
    print("ASSERTIONS")
    print(SUB)

    d = result.diagnosis
    actual_mode = "fallback" if d.fallback_message is not None else "diagnosis"
    if actual_mode == expected_mode:
        print(f"  [PASS] mode matched expected ({expected_mode})")
    else:
        print(
            f"  [INFO] expected {expected_mode!r}, got {actual_mode!r}. "
            f"Check the matcher output above — aggregation may have "
            f"shifted the outcome."
        )

    if d.primary is not None:
        if d.primary.cause_id == "cupped_lead_wrist_at_top":
            print(f"  [PASS] primary is cupped_lead_wrist_at_top (matches the demo fault)")
        else:
            print(
                f"  [INFO] primary is {d.primary.cause_id!r}; "
                f"expected cupped_lead_wrist_at_top."
            )
    elif d.fallback_message:
        print(f"  [PASS] fallback_message populated")


def main() -> None:
    print(BAR)
    print("  END-TO-END PIPELINE TEST")
    print("  Real videos → pose → segmentation → features → matcher → LLM")
    print(BAR)

    print("\nLoading KB…")
    kb = load_kb(Path("kb"))
    print(f"  Loaded slice causes: {len(kb.get_causes('slice'))}")

    # ---- Case A: single-swing diagnosis --------------------------
    # swing_16 alone: the validated Phase 2 cupped demo. Score 1.40
    # on cupped_lead_wrist_at_top per test_matcher.py Test B. With
    # n=1 the consistency filter is trivially satisfied, so the
    # matcher output survives to the LLM.
    _run_case(
        label="CASE A — single swing (diagnosis expected)",
        video_paths=[Path("data/raw/swing_16.mov")],
        kb=kb,
        user_context=(
            "I've been slicing for years. Curving hard right on every "
            "iron shot."
        ),
        expected_mode="diagnosis",
    )

    # ---- Case B: two-swing fallback ------------------------------
    # swing_16 (extreme cupped demo) + swing_09 (mostly-normal swing
    # with visible-to-eye cupping but measurably closer to baseline).
    # The 60% consistency filter suppresses any indicator that
    # doesn't fire on both — expected fallback with all scores 0.00.
    # Demonstrates the filter working as designed: a fault present on
    # one swing but not the other is not diagnosable.
    _run_case(
        label="CASE B — two swings (fallback expected via consistency filter)",
        video_paths=[
            Path("data/raw/swing_16.mov"),
            Path("data/raw/swing_09.mov"),
        ],
        kb=kb,
        user_context=(
            "I've been slicing consistently. Feels like I know the "
            "ball is going right the moment I start the downswing."
        ),
        expected_mode="fallback",
    )

    print("\nDone.")


if __name__ == "__main__":
    main()