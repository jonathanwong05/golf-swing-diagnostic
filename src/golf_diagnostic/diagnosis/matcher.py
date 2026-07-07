"""
KB matcher: score causes against a user's uploaded swings.

Given the symptom the user reported, their per-swing SwingFeatures,
their cross-swing AggregatedFeatures, and the loaded KnowledgeBase,
return a ranked list of causes with detail on which indicators
matched.

The matcher does not decide what to show the user — that's the
LLM layer's job. It produces evidence, sorted by evidence strength.
"""

from __future__ import annotations

import math
import operator
from dataclasses import dataclass, field

from golf_diagnostic.features.schema import (
    AggregatedFeatures,
    SwingFeatures,
)
from golf_diagnostic.kb.loader import (
    BaselineEntry,
    Cause,
    Indicator,
    KnowledgeBase,
)


CONSISTENCY_THRESHOLD = 0.60
FALLBACK_SCORE_FLOOR = 0.5

_OPERATORS = {
    "gt": operator.gt,
    "lt": operator.lt,
    "gte": operator.ge,
    "lte": operator.le,
    "abs_gt": lambda x, t: abs(x) > t,
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchedIndicator:
    """A cause-level match record for a single indicator."""
    indicator: Indicator
    hit_count: int          # swings where the indicator fired
    swing_count: int        # total swings evaluated
    representative_value: float
    """
    For raw/zscore modes: mean of the feature across swings where the
    indicator fired. For stddev_gt mode: the aggregate's stddev for the
    feature. NaN if no per-swing hits (stddev_gt indicators always have
    a value; per-swing indicators may not).
    """


@dataclass(frozen=True)
class RankedCause:
    """A cause with its computed score and matched-indicator evidence."""
    cause: Cause
    score: float
    matched_indicators: list[MatchedIndicator] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-swing indicator evaluation
# ---------------------------------------------------------------------------

def _evaluate_per_swing(
    ind: Indicator,
    swing: SwingFeatures,
    baseline: dict[str, BaselineEntry],
) -> bool:
    """
    Evaluate a raw or zscore indicator against a single swing.

    Returns False on NaN input (unavailable feature never matches).
    stddev_gt is not handled here — it's cross-swing by construction.
    """
    value = swing.get(ind.feature)
    if not math.isfinite(value):
        return False

    if ind.mode == "raw":
        x = value
    elif ind.mode == "zscore":
        b = baseline[ind.feature]
        if not math.isfinite(b.stddev) or b.stddev < 1e-9:
            # Guarded at KB load time, but defensive here too.
            return False
        x = (value - b.mean) / b.stddev
    else:
        # stddev_gt handled elsewhere; treat other modes as unknown.
        raise ValueError(f"Unexpected mode for per-swing eval: {ind.mode!r}")

    op = _OPERATORS[ind.operator]
    return bool(op(x, ind.threshold))


def _evaluate_stddev(
    ind: Indicator,
    aggregate: AggregatedFeatures,
) -> tuple[bool, float]:
    """
    Evaluate a stddev_gt indicator against the aggregate. Returns
    (matched, feature_stddev). NaN stddev never matches.
    """
    stddev = aggregate.get(ind.feature, "stddev")
    if not math.isfinite(stddev):
        return False, float("nan")
    matched = bool(_OPERATORS[ind.operator](stddev, ind.threshold))
    return matched, stddev


# ---------------------------------------------------------------------------
# Cause scoring
# ---------------------------------------------------------------------------

def _score_indicator_at_cause_level(
    ind: Indicator,
    swings: list[SwingFeatures],
    aggregate: AggregatedFeatures,
    baseline: dict[str, BaselineEntry],
) -> MatchedIndicator | None:
    """
    Return a MatchedIndicator if this indicator matches at the cause
    level (per consistency filter), else None.

    "Matches" means:
    - stddev_gt: the aggregate's stddev crosses the threshold.
    - raw / zscore: the indicator fires on >= CONSISTENCY_THRESHOLD
      fraction of swings.
    """
    if ind.mode == "stddev_gt":
        matched, stddev = _evaluate_stddev(ind, aggregate)
        if not matched:
            return None
        return MatchedIndicator(
            indicator=ind,
            hit_count=aggregate.n_swings,  # aggregate-level, all swings
            swing_count=aggregate.n_swings,
            representative_value=stddev,
        )

    # Per-swing evaluation
    hits: list[float] = []
    for swing in swings:
        if _evaluate_per_swing(ind, swing, baseline):
            v = swing.get(ind.feature)
            hits.append(v)

    fraction = len(hits) / len(swings)
    if fraction < CONSISTENCY_THRESHOLD:
        return None

    representative = sum(hits) / len(hits)  # mean of hit values
    return MatchedIndicator(
        indicator=ind,
        hit_count=len(hits),
        swing_count=len(swings),
        representative_value=representative,
    )


def _score_cause(
    cause: Cause,
    swings: list[SwingFeatures],
    aggregate: AggregatedFeatures,
    baseline: dict[str, BaselineEntry],
) -> RankedCause:
    matched: list[MatchedIndicator] = []
    score = 0.0
    for ind in cause.indicators:
        m = _score_indicator_at_cause_level(ind, swings, aggregate, baseline)
        if m is not None:
            matched.append(m)
            score += ind.confidence_weight
    return RankedCause(cause=cause, score=score, matched_indicators=matched)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_symptom(
    symptom: str,
    swings: list[SwingFeatures],
    aggregate: AggregatedFeatures,
    kb: KnowledgeBase,
) -> list[RankedCause]:
    """
    Score every cause for the reported symptom and return them sorted
    descending by score. Ties preserved in KB author order (list
    order in the YAML file) via Python's stable sort.

    Returns an empty list if the symptom has no loaded KB.
    """
    if not swings:
        raise ValueError("match_symptom requires at least one swing")

    causes = kb.get_causes(symptom)
    if not causes:
        return []

    ranked = [
        _score_cause(cause, swings, aggregate, kb.baseline)
        for cause in causes
    ]
    ranked.sort(key=lambda r: -r.score)
    return ranked


def should_fall_back(ranked: list[RankedCause]) -> bool:
    """
    True when the ranked results don't clear the evidence bar for
    presenting causes to the user. Fires when:
    - the list is empty (no KB for this symptom), or
    - no cause has any matched indicators, or
    - the top-scoring cause has score < FALLBACK_SCORE_FLOOR
      (effectively "only a single weak corroborating indicator fired").

    Callers should surface the "no clear cause detected" LLM template
    when this returns True.
    """
    if not ranked:
        return True
    top = ranked[0]
    if not top.matched_indicators:
        return True
    return top.score < FALLBACK_SCORE_FLOOR