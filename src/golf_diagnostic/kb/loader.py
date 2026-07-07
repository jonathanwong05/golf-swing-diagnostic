"""
Knowledge base loader.

Loads per-symptom KB YAML files from a directory and validates them
against the schema (FEATURE_NAMES) and baseline (kb/baseline.yaml).
Every reference to a feature must resolve to a real schema field,
and every zscore-mode indicator must reference a feature with a
finite baseline stddev.

Fails loud at load time on any inconsistency. This is the
counterpart to the orchestrator's import-time schema coverage
assertion — the KB should never silently reference a feature that
doesn't exist.

Usage:
    kb = load_kb(Path("kb"))
    causes = kb.get_causes("slice")
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from golf_diagnostic.features.schema import FEATURE_NAMES


SUPPORTED_SYMPTOMS: frozenset[str] = frozenset({
    "slice",
    "hook",
    "pull",
    "push",
    "fat_contact",
    "thin_contact",
    "lack_of_distance",
    "inconsistent_contact",
    "shank",
})

_FEATURE_NAMES_SET: frozenset[str] = frozenset(FEATURE_NAMES)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Indicator(BaseModel):
    feature: str
    mode: Literal["raw", "zscore", "stddev_gt"]
    operator: Literal["gt", "lt", "gte", "lte", "abs_gt"]
    threshold: float
    confidence_weight: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""

    @field_validator("feature")
    @classmethod
    def feature_must_be_known(cls, v: str) -> str:
        if v not in _FEATURE_NAMES_SET:
            raise ValueError(
                f"Unknown feature {v!r}; not in schema.FEATURE_NAMES"
            )
        return v


class Feel(BaseModel):
    feel: str
    best_for: str = ""
    why_it_works: str = ""


class Drill(BaseModel):
    name: str
    youtube_url: str = ""


class Fix(BaseModel):
    technical_instruction: str


class Cause(BaseModel):
    cause_id: str
    category: Literal["swing", "setup"]
    confidence: Literal["validated", "plausible", "weak"]
    description: str
    indicators: list[Indicator] = Field(min_length=1)
    fix: Fix
    feels: list[Feel] = Field(min_length=1)
    drills: list[Drill] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BaselineEntry:
    mean: float
    stddev: float  # NaN if n < 2
    n: int


def _load_baseline(path: Path) -> dict[str, BaselineEntry]:
    if not path.exists():
        raise FileNotFoundError(
            f"Baseline file not found: {path}. "
            "Run scripts/regenerate_baseline.py to generate it."
        )
    with path.open() as f:
        raw = yaml.safe_load(f)

    out: dict[str, BaselineEntry] = {}
    for name, entry in raw.items():
        if name not in _FEATURE_NAMES_SET:
            raise ValueError(
                f"Baseline references unknown feature {name!r}. "
                "Regenerate baseline after schema changes."
            )
        mean = entry.get("mean")
        stddev = entry.get("stddev")
        n = entry.get("n", 0)
        out[name] = BaselineEntry(
            mean=float("nan") if mean is None else float(mean),
            stddev=float("nan") if stddev is None else float(stddev),
            n=int(n),
        )
    missing = _FEATURE_NAMES_SET - out.keys()
    if missing:
        raise ValueError(
            f"Baseline missing {len(missing)} features: "
            f"{sorted(missing)[:5]}... Regenerate baseline."
        )
    return out


# ---------------------------------------------------------------------------
# KnowledgeBase container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KnowledgeBase:
    causes_by_symptom: dict[str, list[Cause]]
    baseline: dict[str, BaselineEntry]

    def get_causes(self, symptom: str) -> list[Cause]:
        """Return causes for a symptom in author-declared priority order."""
        if symptom not in SUPPORTED_SYMPTOMS:
            raise KeyError(f"Unsupported symptom: {symptom!r}")
        return self.causes_by_symptom.get(symptom, [])

    def loaded_symptoms(self) -> list[str]:
        """Which symptoms currently have a KB file loaded (sorted)."""
        return sorted(self.causes_by_symptom.keys())


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_symptom_file(path: Path) -> list[Cause]:
    with path.open() as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, list):
        raise ValueError(
            f"{path.name}: top level must be a list of causes, got {type(raw).__name__}"
        )

    causes: list[Cause] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(raw):
        try:
            cause = Cause(**entry)
        except ValidationError as e:
            raise ValueError(f"{path.name}: cause #{i}: {e}") from None
        if cause.cause_id in seen_ids:
            raise ValueError(
                f"{path.name}: duplicate cause_id {cause.cause_id!r}"
            )
        seen_ids.add(cause.cause_id)
        causes.append(cause)
    return causes


def _cross_validate(
    causes_by_symptom: dict[str, list[Cause]],
    baseline: dict[str, BaselineEntry],
) -> None:
    """Cross-file validation that can't happen inside Pydantic models alone."""
    for symptom, causes in causes_by_symptom.items():
        for cause in causes:
            for ind in cause.indicators:
                if ind.mode == "zscore":
                    b = baseline[ind.feature]  # existence guaranteed above
                    if not math.isfinite(b.stddev) or b.stddev < 1e-9:
                        raise ValueError(
                            f"{symptom}/{cause.cause_id}: indicator on "
                            f"{ind.feature!r} uses mode=zscore but baseline "
                            f"stddev is {b.stddev} (n={b.n}). "
                            "Use mode=raw or regenerate baseline."
                        )
                if ind.mode == "stddev_gt" and ind.threshold < 0:
                    raise ValueError(
                        f"{symptom}/{cause.cause_id}: stddev_gt threshold "
                        f"must be non-negative, got {ind.threshold}"
                    )


def load_kb(kb_dir: Path) -> KnowledgeBase:
    """
    Load and validate the knowledge base.

    Missing symptom files are OK during authoring — the loader returns
    whatever's present. Unexpected filenames (typos, wrong casing)
    fail hard.
    """
    if not kb_dir.is_dir():
        raise FileNotFoundError(f"KB directory not found: {kb_dir}")

    baseline = _load_baseline(kb_dir / "baseline.yaml")

    causes_by_symptom: dict[str, list[Cause]] = {}
    for path in sorted(kb_dir.glob("*.yaml")):
        if path.name == "baseline.yaml":
            continue
        stem = path.stem
        if stem not in SUPPORTED_SYMPTOMS:
            raise ValueError(
                f"Unexpected KB file {path.name}. "
                f"Expected one of: {sorted(SUPPORTED_SYMPTOMS)}"
            )
        causes_by_symptom[stem] = _load_symptom_file(path)

    _cross_validate(causes_by_symptom, baseline)
    return KnowledgeBase(
        causes_by_symptom=causes_by_symptom,
        baseline=baseline,
    )