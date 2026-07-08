"""
KB matcher: score causes against a user's uploaded swings.

Two public entry points:

- ``match_symptom`` — the symptom-driven path. Score every cause
  for the reported symptom, return them ranked. Original v1 mode.
- ``match_general`` — the symptom-optional path (Phase 5.1). Pool
  every unique cause across all loaded symptoms, deduplicate by
  ``cause_id``, score and rank. For users who don't want to select
  a specific ball-flight symptom.

Both return ``list[RankedCause]`` and share the same fallback logic
via ``should_fall_back``. The matcher does not decide what to show
the user — that's the LLM layer's job. It produces evidence, sorted
by evidence strength.

Shared-cause handling (used by ``match_general``)
-------------------------------------------------
When a ``cause_id`` appears across multiple symptom files, this
module enforces IDENTITY on diagnostic fields (indicators, fix,
category) and POOLS coaching content (feels, drills):

- Diagnostic fields must match byte-for-byte on matcher-relevant
  attributes. Divergence would mean scoring depends on which
  symptom's YAML we visited first — a silent bug. Raise loud.
- Coaching fields are allowed (and expected) to differ per symptom
  — a shank-context feel for early extension reads differently
  than a fat-contact-context feel for the same fault. General mode
  unions all feels and drills across occurrences (dedup by text /
  name, preserving first-occurrence order) so the LLM has the full
  coaching vocabulary available when it picks.
"""

from __future__ import annotations

import math
import operator
from collections import defaultdict
from dataclasses import dataclass, field

from golf_diagnostic.features.schema import (
    AggregatedFeatures,
    SwingFeatures,
)
from golf_diagnostic.kb.loader import (
    BaselineEntry,
    Cause,
    Drill,
    Feel,
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
# Cross-symptom deduplication + coaching pool (used by match_general)
# ---------------------------------------------------------------------------

def _fmt_indicators(inds: list[Indicator]) -> str:
    if not inds:
        return "        (none)"
    return "\n".join(
        f"        - {i.feature} / {i.mode} {i.operator} {i.threshold} "
        f"(w={i.confidence_weight})"
        for i in inds
    )


def _indicators_matcher_equal(
    a: list[Indicator], b: list[Indicator]
) -> bool:
    """Compare two indicator lists on matcher-relevant fields only.

    Excludes ``Indicator.reasoning``: it is per-file documentation
    authored by whoever wrote the KB entry, and may vary across
    symptom files without any diagnostic significance. Different
    reasoning strings for the same physical fault ("primary
    slice indicator" vs "corroborator for lack of distance") are
    expected, not violations. Neither the matcher nor the LLM
    reads the reasoning field.

    Everything else on ``Indicator`` (feature, mode, operator,
    threshold, confidence_weight) is diagnostic and must match.
    """
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        xk = (x.feature, x.mode, x.operator, x.threshold, x.confidence_weight)
        yk = (y.feature, y.mode, y.operator, y.threshold, y.confidence_weight)
        if xk != yk:
            return False
    return True


def _assert_diagnostic_identity(
    existing: Cause,
    cause: Cause,
    origin_a: str | None = None,
    origin_b: str | None = None,
) -> None:
    """
    Enforce the Phase 3 consistency rule on diagnostic fields.

    Two causes sharing a ``cause_id`` must agree on the fields the
    matcher's scoring depends on:

    - ``indicators`` (matcher-relevant fields; see
      ``_indicators_matcher_equal``)
    - ``fix.technical_instruction`` — the authoritative fix for
      the fault, quoted verbatim to the user
    - ``category`` — swing vs. setup, intrinsic to the cause

    Divergence on any of these means general-mode scoring depends
    on which symptom's YAML we visited first — a silent bug. Raise
    ``ValueError`` loud.

    Coaching fields (``feels``, ``drills``) are NOT checked here.
    They are expected to differ per symptom (a shank-context feel
    for early extension reads differently than a fat-contact-context
    feel) and are handled via pooling in
    ``_collect_unique_causes``.

    Also NOT checked: ``description`` (prose may be tailored per
    symptom), ``confidence`` (Phase 2 metadata not read by matcher).

    Origin symptom labels are threaded through for actionable
    error messages when running against a real KB.
    """
    cid = existing.cause_id
    tag_a = f"{origin_a}.yaml" if origin_a else "existing"
    tag_b = f"{origin_b}.yaml" if origin_b else "new"

    if not _indicators_matcher_equal(existing.indicators, cause.indicators):
        raise ValueError(
            f"cause_id {cid!r} has divergent indicators.\n"
            f"    {tag_a} ({len(existing.indicators)} indicators):\n"
            f"{_fmt_indicators(existing.indicators)}\n"
            f"    {tag_b} ({len(cause.indicators)} indicators):\n"
            f"{_fmt_indicators(cause.indicators)}\n"
            f"    Phase 3 consistency rule requires identical "
            f"feature/mode/operator/threshold/weight for shared causes."
        )

    if existing.fix.technical_instruction != cause.fix.technical_instruction:
        raise ValueError(
            f"cause_id {cid!r} has divergent fix.technical_instruction.\n"
            f"    {tag_a}: {existing.fix.technical_instruction!r}\n"
            f"    {tag_b}: {cause.fix.technical_instruction!r}"
        )

    if existing.category != cause.category:
        raise ValueError(
            f"cause_id {cid!r} has divergent category "
            f"({tag_a}={existing.category!r} vs {tag_b}={cause.category!r})."
        )


def _pool_feels(feels_lists: list[list[Feel]]) -> list[Feel]:
    """
    Union feels across a cause's occurrences, deduplicating by
    ``feel`` text. Order: first-occurrence wins.

    The pooled list is the coaching vocabulary available to the LLM
    in general mode. More options ≥ symptom-mode subset.
    """
    seen: dict[str, Feel] = {}
    for feels in feels_lists:
        for f in feels:
            if f.feel not in seen:
                seen[f.feel] = f
    return list(seen.values())


def _pool_drills(drills_lists: list[list[Drill]]) -> list[Drill]:
    """
    Union drills across a cause's occurrences, deduplicating by
    ``name``. Order: first-occurrence wins.
    """
    seen: dict[str, Drill] = {}
    for drills in drills_lists:
        for d in drills:
            if d.name not in seen:
                seen[d.name] = d
    return list(seen.values())


def collect_unique_causes(kb: KnowledgeBase) -> list[Cause]:
    """
    Walk every loaded symptom's causes, deduplicate by ``cause_id``,
    and return a canonical list.

    Public because ``output_schema.validate_against_kb`` uses it in
    general mode (Phase 5.1): the validator has to check ``feel_id``
    and ``drill_ids`` against the exact ``Cause`` objects the LLM
    saw, which in general mode carry the pooled coaching content.

    For each unique ``cause_id`` occurring in 2+ symptom files:

    1. Enforce diagnostic identity via ``_assert_diagnostic_identity``
       across all occurrences. Raises ``ValueError`` on divergence.
    2. Pool ``feels`` and ``drills`` across all occurrences (dedup by
       text/name, preserving first-occurrence order).
    3. Emit a canonical ``Cause`` built via ``model_copy`` from the
       first occurrence, with the pooled coaching content substituted.

    Causes appearing in exactly one symptom pass through unchanged.

    Iteration order is deterministic: symptoms in
    ``kb.loaded_symptoms()`` order (stable from the loader), causes
    in KB author order within each symptom.

    Empty list if no symptoms are loaded.
    """
    grouped: dict[str, list[tuple[str, Cause]]] = defaultdict(list)
    for symptom in kb.loaded_symptoms():
        for cause in kb.get_causes(symptom):
            grouped[cause.cause_id].append((symptom, cause))

    canonical_causes: list[Cause] = []
    for cause_id, occurrences in grouped.items():
        first_symptom, first_cause = occurrences[0]

        # Enforce diagnostic identity on all subsequent occurrences.
        for other_symptom, other_cause in occurrences[1:]:
            _assert_diagnostic_identity(
                first_cause, other_cause,
                origin_a=first_symptom, origin_b=other_symptom,
            )

        if len(occurrences) == 1:
            # Only one file — nothing to pool.
            canonical_causes.append(first_cause)
            continue

        # Pool coaching content across all occurrences.
        pooled_feels = _pool_feels([c.feels for _, c in occurrences])
        pooled_drills = _pool_drills([c.drills for _, c in occurrences])
        canonical = first_cause.model_copy(
            update={"feels": pooled_feels, "drills": pooled_drills}
        )
        canonical_causes.append(canonical)

    return canonical_causes


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


def match_general(
    swings: list[SwingFeatures],
    aggregate: AggregatedFeatures,
    kb: KnowledgeBase,
) -> list[RankedCause]:
    """
    Score every unique cause across all loaded symptoms and return
    them sorted descending by score. Used when the user has not
    reported a specific ball-flight symptom (Phase 5.1 general
    analysis mode).

    Candidate pool: ``collect_unique_causes(kb)``. Shared causes
    (appearing in 2+ symptom files) are deduplicated by cause_id.
    Their diagnostic fields (indicators, fix, category) must match
    across files — enforced at runtime. Their coaching fields (feels,
    drills) are pooled: the general-mode ``Cause`` carries the union
    of feels + drills from every file that hosts it.

    Consequence: a fault demo's top cause score under general mode
    is identical to its top cause score under the appropriate
    symptom mode. General mode surfaces MORE candidates (~22 unique
    causes vs. 3-5 per symptom) and shared causes carry MORE feels /
    drills (the union across their symptom files), giving the LLM a
    richer coaching vocabulary to select from.

    Ties preserved in traversal order (see ``collect_unique_causes``).

    Raises ``ValueError`` if ``swings`` is empty, or if two causes
    with the same ``cause_id`` diverge on any diagnostic field
    (see ``_assert_diagnostic_identity``).

    Returns an empty list if no symptoms are loaded.
    """
    if not swings:
        raise ValueError("match_general requires at least one swing")

    causes = collect_unique_causes(kb)
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
    when this returns True. Applies to both ``match_symptom`` and
    ``match_general`` output — the same 0.5 floor governs both modes.
    """
    if not ranked:
        return True
    top = ranked[0]
    if not top.matched_indicators:
        return True
    return top.score < FALLBACK_SCORE_FLOOR