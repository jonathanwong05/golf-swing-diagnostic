"""
Sanity tests for diagnosis/output_schema.py.

Covers:
- Pydantic structural validation (field constraints, exactly-one-path
  model validator)
- validate_against_kb semantic validation (cause_id in ranked list,
  feel_id and drill_ids in range, no duplicate causes across
  primary/secondary, no-op on fallback)

Uses the real slice.yaml KB so cause_ids match reality. If slice.yaml
did not load, semantic tests are skipped and a warning is printed.

Run from the repo root:
    python scripts/test_output_schema.py
"""

from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from golf_diagnostic.diagnosis.output_schema import (
    CauseExplanation,
    DiagnosisValidationError,
    DiagnosticOutput,
    validate_against_kb,
)
from golf_diagnostic.kb.loader import load_kb


# ---------------------------------------------------------------------
# Tiny test helpers. Deliberately not pytest — matches the repo pattern.
# ---------------------------------------------------------------------


def _tag(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _report(label: str, ok: bool, detail: str = "") -> None:
    line = f"  [{_tag(ok)}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def expect_ok(label: str, thunk: Callable[[], object]) -> None:
    try:
        thunk()
        _report(label, True)
    except Exception as e:  # noqa: BLE001 — intentional broad catch in test
        _report(label, False, f"unexpected {type(e).__name__}: {e}")


def expect_error(
    label: str,
    thunk: Callable[[], object],
    expected_type: type,
    fragment: str | None = None,
) -> None:
    try:
        thunk()
    except expected_type as e:
        if fragment and fragment.lower() not in str(e).lower():
            _report(
                label,
                False,
                f"{expected_type.__name__} raised but message missing "
                f"{fragment!r}: {e}",
            )
        else:
            _report(label, True)
        return
    except Exception as e:  # noqa: BLE001
        _report(
            label,
            False,
            f"expected {expected_type.__name__}, got "
            f"{type(e).__name__}: {e}",
        )
        return
    _report(label, False, f"expected {expected_type.__name__}, got no error")


def _cause(cause_id: str = "cupped_lead_wrist_at_top", **overrides) -> CauseExplanation:
    """Minimal CauseExplanation for structural tests. Override any field."""
    fields = dict(
        cause_id=cause_id,
        feel_id=0,
        technical_explanation="stub",
        bridge_to_feel="stub",
    )
    fields.update(overrides)
    return CauseExplanation(**fields)


# ---------------------------------------------------------------------
# Test body
# ---------------------------------------------------------------------


def main() -> None:
    print("Loading KB…")
    kb = load_kb(Path("kb"))
    slice_causes = kb.get_causes("slice")

    if not slice_causes:
        print("  slice.yaml not loaded — semantic tests will be skipped.")
        cupped = None
        ranked_ids: list[str] = []
        n_feels = n_drills = 0
    else:
        cupped = next(
            (c for c in slice_causes if c.cause_id == "cupped_lead_wrist_at_top"),
            slice_causes[0],
        )
        n_feels = len(cupped.feels)
        n_drills = len(cupped.drills)
        ranked_ids = [c.cause_id for c in slice_causes]
        print(
            f"  Loaded {len(slice_causes)} slice causes. "
            f"Using {cupped.cause_id!r} ({n_feels} feel(s), "
            f"{n_drills} drill(s))."
        )

    # ---- Structural: happy paths ------------------------------------
    print("\nStructural — happy paths")

    expect_ok(
        "Normal diagnosis parses",
        lambda: DiagnosticOutput(
            summary="Face opening at the top, held open into impact.",
            primary=_cause(cause_id=cupped.cause_id if cupped else "any_id"),
        ),
    )

    expect_ok(
        "Normal diagnosis with 2 secondary parses",
        lambda: DiagnosticOutput(
            summary="Face open at top with body compensations.",
            primary=_cause(cause_id="a"),
            secondary=[_cause(cause_id="b"), _cause(cause_id="c")],
        ),
    )

    expect_ok(
        "Fallback parses",
        lambda: DiagnosticOutput(
            summary="Nothing jumped out clearly.",
            fallback_message="Shoulders were mildly open at impact but did not clear threshold.",
        ),
    )

    expect_ok(
        "CauseExplanation with drill_ids parses",
        lambda: _cause(drill_ids=[0, 1]),
    )

    # ---- Structural: exactly-one-path model validator ---------------
    print("\nStructural — exactly-one-path")

    expect_error(
        "Both primary AND fallback populated rejected",
        lambda: DiagnosticOutput(
            summary="x",
            primary=_cause(),
            fallback_message="also here",
        ),
        ValidationError,
        fragment="cannot populate both",
    )

    expect_error(
        "Neither primary nor fallback populated rejected",
        lambda: DiagnosticOutput(summary="x"),
        ValidationError,
        fragment="either primary",
    )

    expect_error(
        "Fallback with non-empty secondary rejected",
        lambda: DiagnosticOutput(
            summary="x",
            fallback_message="y",
            secondary=[_cause()],
        ),
        ValidationError,
        fragment="secondary must be empty",
    )

    # ---- Structural: field-level constraints ------------------------
    print("\nStructural — field constraints")

    expect_error(
        "feel_id negative rejected",
        lambda: CauseExplanation(
            cause_id="x",
            feel_id=-1,
            technical_explanation="x",
            bridge_to_feel="x",
        ),
        ValidationError,
    )

    expect_error(
        "Empty summary rejected",
        lambda: DiagnosticOutput(summary="", fallback_message="y"),
        ValidationError,
    )

    expect_error(
        "Empty technical_explanation rejected",
        lambda: CauseExplanation(
            cause_id="x",
            feel_id=0,
            technical_explanation="",
            bridge_to_feel="x",
        ),
        ValidationError,
    )

    expect_error(
        "Empty bridge_to_feel rejected",
        lambda: CauseExplanation(
            cause_id="x",
            feel_id=0,
            technical_explanation="x",
            bridge_to_feel="",
        ),
        ValidationError,
    )

    expect_error(
        "Secondary with 3 items rejected (max 2)",
        lambda: DiagnosticOutput(
            summary="x",
            primary=_cause(cause_id="p"),
            secondary=[_cause(cause_id=f"s{i}") for i in range(3)],
        ),
        ValidationError,
    )

    expect_error(
        "drill_ids with 3 items rejected (max 2)",
        lambda: _cause(drill_ids=[0, 1, 2]),
        ValidationError,
    )

    # ---- Semantic: validate_against_kb ------------------------------
    if cupped is None:
        print("\nSemantic tests skipped (no slice KB loaded).")
        print("\nDone.")
        return

    print("\nSemantic — happy paths")

    expect_ok(
        "Valid normal diagnosis passes",
        lambda: validate_against_kb(
            DiagnosticOutput(
                summary="x",
                primary=_cause(cause_id=cupped.cause_id),
            ),
            ranked_ids,
            kb,
            "slice",
        ),
    )

    expect_ok(
        "Fallback output no-ops (nothing to check)",
        lambda: validate_against_kb(
            DiagnosticOutput(summary="x", fallback_message="y"),
            ranked_ids,
            kb,
            "slice",
        ),
    )

    if n_drills > 0:
        expect_ok(
            "Valid diagnosis with valid drill_id passes",
            lambda: validate_against_kb(
                DiagnosticOutput(
                    summary="x",
                    primary=_cause(
                        cause_id=cupped.cause_id,
                        drill_ids=list(range(min(n_drills, 2))),
                    ),
                ),
                ranked_ids,
                kb,
                "slice",
            ),
        )

    print("\nSemantic — failures")

    expect_error(
        "Hallucinated cause_id rejected",
        lambda: validate_against_kb(
            DiagnosticOutput(
                summary="x",
                primary=_cause(cause_id="not_a_real_cause"),
            ),
            ranked_ids,
            kb,
            "slice",
        ),
        DiagnosisValidationError,
        fragment="not in the ranked list",
    )

    expect_error(
        "Real cause_id but absent from ranked list rejected",
        lambda: validate_against_kb(
            DiagnosticOutput(
                summary="x",
                primary=_cause(cause_id=cupped.cause_id),
            ),
            [],  # empty ranked list simulates "not passed in this call"
            kb,
            "slice",
        ),
        DiagnosisValidationError,
        fragment="not in the ranked list",
    )

    if len(slice_causes) >= 2:
        expect_error(
            "Duplicate cause across primary/secondary rejected",
            lambda: validate_against_kb(
                DiagnosticOutput(
                    summary="x",
                    primary=_cause(cause_id=cupped.cause_id),
                    secondary=[_cause(cause_id=cupped.cause_id)],
                ),
                ranked_ids,
                kb,
                "slice",
            ),
            DiagnosisValidationError,
            fragment="more than once",
        )

    expect_error(
        "feel_id out of range rejected",
        lambda: validate_against_kb(
            DiagnosticOutput(
                summary="x",
                primary=_cause(
                    cause_id=cupped.cause_id,
                    feel_id=n_feels + 5,
                ),
            ),
            ranked_ids,
            kb,
            "slice",
        ),
        DiagnosisValidationError,
        fragment="out of range",
    )

    if n_drills > 0:
        expect_error(
            "drill_id out of range rejected",
            lambda: validate_against_kb(
                DiagnosticOutput(
                    summary="x",
                    primary=_cause(
                        cause_id=cupped.cause_id,
                        drill_ids=[n_drills + 3],
                    ),
                ),
                ranked_ids,
                kb,
                "slice",
            ),
            DiagnosisValidationError,
            fragment="out of range",
        )
    else:
        expect_error(
            "drill_ids populated when cause has 0 drills rejected",
            lambda: validate_against_kb(
                DiagnosticOutput(
                    summary="x",
                    primary=_cause(
                        cause_id=cupped.cause_id,
                        drill_ids=[0],
                    ),
                ),
                ranked_ids,
                kb,
                "slice",
            ),
            DiagnosisValidationError,
            fragment="no drills",
        )

    print("\nDone.")


if __name__ == "__main__":
    main()