"""End-to-end sanity script for general-mode pipeline (Phase 5.1).

Runs the full ``analyze_swings`` chain with ``symptom=None``,
exercising the general-mode paths in matcher, prompt, LLM client,
and validator. HITS THE ANTHROPIC API — estimated cost ~$0.02.

Two cases, both in general-mode diagnosis:

- **Case A**: single swing with a strong pattern. swing_16
  (cupped-wrist fault demo) → matcher finds
  ``cupped_lead_wrist_at_top`` at 1.40. LLM should describe the
  pattern as an observation, not as a slice explanation.

- **Case B**: two swings with high inter-swing variance. swing_16
  (very cupped) + swing_09 (mildly cupped) → the wrist-position
  stddev across the two swings is genuinely large, so
  ``inconsistent_top_of_backswing`` fires. General mode
  legitimately surfaces this as "here's what varies across your
  swings" rather than falling back — this is a design consequence
  of general-mode pooling + ``stddev_gt`` indicators bypassing the
  consistency filter, and is the correct behavior.

Note on the missing "general-mode fallback" case: general fallback
uses the same code path as symptom-mode fallback (already exercised
in Phase 4 ``scripts/test_pipeline.py``) and the same prompt
branching as ``scripts/test_general_prompt.py``. General fallback
is also structurally harder to trigger than symptom fallback
because the variance-cause pool is always available. Not worth an
extra API call to exercise here.

Run from project root::

    python scripts/test_general_pipeline.py

Requires:
- ``ANTHROPIC_API_KEY`` in env
- ``data/raw/swing_16.mov`` and ``data/raw/swing_09.mov``
- Pose NPZ cache in ``data/processed/`` (or the script re-extracts,
  ~15s per video)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from golf_diagnostic.kb.loader import load_kb
from golf_diagnostic.pipeline import analyze_swings

REPO_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = REPO_ROOT / "kb"
RAW_DIR = REPO_ROOT / "data" / "raw"
CACHE_DIR = REPO_ROOT / "data" / "processed"

SWING_16 = RAW_DIR / "swing_16.mov"
SWING_09 = RAW_DIR / "swing_09.mov"


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


def _print_diagnosis(diagnosis) -> None:
    print(f"\n  summary: {diagnosis.summary}")
    if diagnosis.primary is not None:
        p = diagnosis.primary
        print(f"\n  primary.cause_id: {p.cause_id}")
        print(f"  primary.feel_id: {p.feel_id}")
        print(f"  primary.drill_ids: {p.drill_ids}")
        print(f"  primary.technical_explanation:")
        print(f"    {p.technical_explanation}")
        print(f"  primary.bridge_to_feel:")
        print(f"    {p.bridge_to_feel}")
    if diagnosis.secondary:
        print(f"\n  {len(diagnosis.secondary)} secondary cause(s):")
        for s in diagnosis.secondary:
            print(f"    - {s.cause_id} (feel_id={s.feel_id})")
    if diagnosis.fallback_message is not None:
        print(f"\n  fallback_message:")
        print(f"    {diagnosis.fallback_message}")


# --------------------------------------------------------------------------
# Test cases
# --------------------------------------------------------------------------

# Words that should NOT appear in general-mode output — they'd
# indicate the LLM assumed a symptom the user didn't report.
_SYMPTOM_LEAK_WORDS = [
    "slic",       # matches "slice", "slicing"
    "hook",
    "curving right",
    "curving left",
    "you're producing a",
    "your ball is starting",
]


def _assert_no_symptom_leak(text: str, where: str) -> None:
    """Fail if the general-mode output leaks symptom-specific framing."""
    text_lower = text.lower()
    for word in _SYMPTOM_LEAK_WORDS:
        _check(
            word.lower() not in text_lower,
            f"{where}: does not contain symptom-leak phrase {word!r}",
        )


def case_a_general_diagnosis(kb) -> None:
    print("\n[A] General diagnosis on swing_16 (cupped demo, symptom=None)")

    if not SWING_16.exists():
        _fail(f"{SWING_16} not found")

    result = analyze_swings(
        video_paths=[SWING_16],
        symptom=None,
        kb=kb,
        user_context="I'm not sure what to work on, just want a general read.",
        cache_dir=CACHE_DIR,
        annotated_output_dir=None,
        verbose=True,
    )

    diagnosis = result.diagnosis
    _check(diagnosis.primary is not None, "primary cause populated (diagnosis mode)")
    _check(diagnosis.fallback_message is None, "fallback_message is None")

    if diagnosis.primary is not None:
        _check(
            diagnosis.primary.cause_id == "cupped_lead_wrist_at_top",
            f"primary cause is cupped_lead_wrist_at_top "
            f"(got {diagnosis.primary.cause_id!r})",
        )

        full_text = (
            diagnosis.summary
            + " "
            + diagnosis.primary.technical_explanation
            + " "
            + diagnosis.primary.bridge_to_feel
        )
        _assert_no_symptom_leak(full_text, "case A primary")

    _print_diagnosis(diagnosis)

    top_score = result.ranked_causes[0].score if result.ranked_causes else 0.0
    print(
        f"\n  matcher top: {result.ranked_causes[0].cause.cause_id} "
        f"@ score {top_score:.2f}"
    )


def case_b_general_variance_diagnosis(kb) -> None:
    """
    Two swings with high inter-swing variance surface a variance-
    based cause in general mode.

    Why this doesn't fall back like the equivalent Phase 4 test:

    - In ``symptom="slice"`` mode, the candidate pool is only
      slice.yaml causes. None are ``stddev_gt`` (variance-based).
      The 60% consistency filter suppresses per-swing indicators
      on this pair (swing_16 fires, swing_09 doesn't). Result: all
      scores = 0, fallback.
    - In general mode (``symptom=None``), the pool includes
      inconsistent_contact.yaml's variance causes. ``stddev_gt``
      indicators bypass the consistency filter, so they see the
      genuinely-high wrist stddev across swing_16 + swing_09 and
      fire. Result: variance diagnosis, not fallback.

    Both behaviors are correct. General mode's is honest and
    useful: this pair really does have variable top-of-backswing
    positions.
    """
    print("\n[B] General variance diagnosis on swing_16 + swing_09 (symptom=None)")

    if not SWING_16.exists() or not SWING_09.exists():
        _fail(f"required videos not found in {RAW_DIR}")

    result = analyze_swings(
        video_paths=[SWING_16, SWING_09],
        symptom=None,
        kb=kb,
        user_context="",
        cache_dir=CACHE_DIR,
        annotated_output_dir=None,
        verbose=True,
    )

    diagnosis = result.diagnosis
    _check(
        diagnosis.primary is not None,
        "primary cause populated (variance diagnosis)",
    )
    _check(diagnosis.fallback_message is None, "fallback_message is None")

    if diagnosis.primary is not None:
        # Any inconsistent_* variance cause is a legitimate primary
        # here — inconsistent_top_of_backswing scores highest per
        # the empirical run, but any variance cause is defensible.
        _check(
            diagnosis.primary.cause_id.startswith("inconsistent_"),
            f"primary is a variance cause (got "
            f"{diagnosis.primary.cause_id!r})",
        )

        # Voice check: LLM should frame this as a variance
        # observation, not a fault diagnosis. Look for at least one
        # variance-language marker.
        full_text = (
            diagnosis.summary
            + " "
            + diagnosis.primary.technical_explanation
            + " "
            + diagnosis.primary.bridge_to_feel
        ).lower()

        variance_markers = [
            "vary",
            "variance",
            "varies",
            "consisten",   # matches consistent, consistency, inconsistent
            "different",
            "swing to swing",
            "swing-to-swing",
            "repeat",
        ]
        found_marker = next(
            (m for m in variance_markers if m in full_text), None
        )
        _check(
            found_marker is not None,
            f"output uses variance/consistency language "
            f"(found marker: {found_marker!r})",
        )

        _assert_no_symptom_leak(full_text, "case B primary")

    _print_diagnosis(diagnosis)

    top = result.ranked_causes[0] if result.ranked_causes else None
    if top is not None:
        print(f"\n  matcher top: {top.cause.cause_id} @ score {top.score:.2f}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _fail("ANTHROPIC_API_KEY is not set")

    print(f"Loading KB from {KB_DIR}")
    kb = load_kb(KB_DIR)
    print(f"Loaded {len(kb.loaded_symptoms())} symptoms")

    case_a_general_diagnosis(kb)
    case_b_general_variance_diagnosis(kb)

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()