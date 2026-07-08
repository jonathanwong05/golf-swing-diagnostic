"""Cross-symptom KB consistency audit.

For every ``cause_id`` that appears in more than one symptom file,
inspect the diagnostic and coaching fields separately and print a
report. Continues through the whole KB regardless of individual
divergences, so a single run surfaces everything at once.

Two categories of finding:

- **Diagnostic divergence** (must match; blocks general mode).
  Fields: indicators (matcher-relevant), fix.technical_instruction,
  category. If any of these differ across files, general mode
  would produce inconsistent scoring depending on which YAML we
  loaded first. Fix in the KB before proceeding.

- **Coaching divergence** (allowed; pooled in general mode).
  Fields: feels, drills. Different symptom files often carry
  different feels for the same underlying fault (a shank-context
  feel for early extension reads differently than a fat-contact
  feel for the same fault). ``match_general`` unions these across
  occurrences, so divergence here is informational.

Fields NOT compared (allowed to differ silently):
- ``description`` — prose tailored per symptom
- ``confidence`` — Phase 2 metadata not read by matcher
- ``Indicator.reasoning`` — per-file authoring notes

Run from project root::

    python scripts/audit_kb_consistency.py

Exit code 0 if the KB has no diagnostic divergences (coaching
divergences alone are OK). Exit 1 if any diagnostic divergence
is found.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from golf_diagnostic.diagnosis.matcher import _assert_diagnostic_identity
from golf_diagnostic.kb.loader import Cause, Drill, Feel, load_kb

REPO_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = REPO_ROOT / "kb"


def _count_unique_feels(feels_lists: list[list[Feel]]) -> int:
    return len({f.feel for feels in feels_lists for f in feels})


def _count_unique_drills(drills_lists: list[list[Drill]]) -> int:
    return len({d.name for drills in drills_lists for d in drills})


def _all_lists_equal(lists: list[list]) -> bool:
    if len(lists) < 2:
        return True
    first = lists[0]
    return all(other == first for other in lists[1:])


def audit_shared_cause(
    cause_id: str,
    occurrences: list[tuple[str, Cause]],
) -> tuple[bool, list[str]]:
    """Audit one shared cause_id.

    Returns ``(has_diagnostic_divergence, output_lines)``.
    """
    lines: list[str] = []
    symptoms = [s for s, _ in occurrences]
    lines.append("")
    lines.append(f"=== {cause_id} ===")
    lines.append(f"Appears in ({len(occurrences)} files): {', '.join(symptoms)}")

    first_sym, first_cause = occurrences[0]

    # ---- Diagnostic identity (hard requirement) ----
    diagnostic_errors: list[str] = []
    for other_sym, other_cause in occurrences[1:]:
        try:
            _assert_diagnostic_identity(
                first_cause, other_cause,
                origin_a=first_sym, origin_b=other_sym,
            )
        except ValueError as e:
            diagnostic_errors.append(str(e))

    if diagnostic_errors:
        lines.append("  ✗ DIAGNOSTIC divergence — BLOCKS general mode:")
        for err in diagnostic_errors:
            lines.append("")
            for text_line in err.splitlines():
                lines.append(f"    {text_line}")
    else:
        lines.append(
            "  ✓ Diagnostic fields identical (indicators / fix / category)"
        )

    # ---- Coaching content (informational; pooled) ----
    all_feels_lists = [c.feels for _, c in occurrences]
    all_drills_lists = [c.drills for _, c in occurrences]

    feels_vary = not _all_lists_equal(all_feels_lists)
    drills_vary = not _all_lists_equal(all_drills_lists)

    if feels_vary or drills_vary:
        lines.append("  ⓘ Coaching content differs (pooled in general mode):")
        if feels_vary:
            n_unique = _count_unique_feels(all_feels_lists)
            n_files = len(occurrences)
            lines.append(
                f"    feels:  {n_unique} unique across {n_files} files "
                f"→ general mode will offer {n_unique} feel(s) for the LLM"
            )
        else:
            lines.append("    feels:  identical across all files")
        if drills_vary:
            n_unique = _count_unique_drills(all_drills_lists)
            n_files = len(occurrences)
            lines.append(
                f"    drills: {n_unique} unique across {n_files} files "
                f"→ general mode will offer {n_unique} drill(s) for the LLM"
            )
        else:
            lines.append("    drills: identical across all files")
    else:
        lines.append("  ✓ Coaching content identical (feels / drills)")

    return bool(diagnostic_errors), lines


def main() -> None:
    print(f"Loading KB from {KB_DIR}")
    kb = load_kb(KB_DIR)
    print(f"Loaded {len(kb.loaded_symptoms())} symptoms")

    # cause_id -> list of (symptom, Cause)
    occurrences: dict[str, list[tuple[str, Cause]]] = defaultdict(list)
    for symptom in kb.loaded_symptoms():
        for cause in kb.get_causes(symptom):
            occurrences[cause.cause_id].append((symptom, cause))

    total_entries = sum(len(v) for v in occurrences.values())
    total_unique = len(occurrences)
    shared = {cid: occs for cid, occs in occurrences.items() if len(occs) > 1}
    unique_only = total_unique - len(shared)

    print()
    print("Cause count summary")
    print("-" * 40)
    print(f"  Total KB entries across symptom files: {total_entries}")
    print(f"  Unique cause_ids:                      {total_unique}")
    print(f"    - appearing in 1 symptom only:       {unique_only}")
    print(f"    - shared across 2+ symptoms:         {len(shared)}")

    if not shared:
        print("\nNo shared causes — nothing to audit.")
        return

    print()
    print("=" * 70)
    print("Shared-cause consistency audit")
    print("=" * 70)

    diagnostic_ok_count = 0
    diagnostic_error_count = 0

    for cause_id in sorted(shared.keys()):
        has_error, out = audit_shared_cause(cause_id, shared[cause_id])
        for ln in out:
            print(ln)
        if has_error:
            diagnostic_error_count += 1
        else:
            diagnostic_ok_count += 1

    print()
    print("=" * 70)
    print(
        f"Summary: {diagnostic_ok_count} shared cause(s) diagnostically consistent, "
        f"{diagnostic_error_count} with diagnostic divergences."
    )
    print("=" * 70)

    if diagnostic_error_count:
        print()
        print(
            "Action required: diagnostic divergences BLOCK general mode.\n"
            "  1. For each error above, pick one file's version as authoritative.\n"
            "  2. Update the other symptom files to match.\n"
            "  3. Re-run this script to verify.\n"
            "\n"
            "Coaching divergences (feels / drills) are handled by pooling in\n"
            "general mode — no action needed there."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()