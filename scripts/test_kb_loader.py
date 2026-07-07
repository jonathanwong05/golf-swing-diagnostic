"""
Sanity-check the KB loader against whatever's currently in kb/.
"""

from __future__ import annotations

from pathlib import Path

from golf_diagnostic.kb.loader import load_kb


REPO_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = REPO_ROOT / "kb"


def main() -> None:
    kb = load_kb(KB_DIR)

    print(f"Baseline features: {len(kb.baseline)}")
    print(f"Loaded symptoms: {kb.loaded_symptoms()}")
    for symptom in kb.loaded_symptoms():
        causes = kb.get_causes(symptom)
        print(f"\n{symptom}: {len(causes)} causes")
        for c in causes:
            n_ind = len(c.indicators)
            n_feels = len(c.feels)
            print(
                f"  - {c.cause_id} "
                f"[{c.category}, {c.confidence}] "
                f"({n_ind} indicators, {n_feels} feels)"
            )

    if not kb.loaded_symptoms():
        print("\n(no symptom KBs loaded yet — expected during Phase 3 authoring)")


if __name__ == "__main__":
    main()