"""
Feature orchestrator.

Runs every Phase 2 extractor on a single swing and merges their
outputs into a `SwingFeatures` instance. This is the layer between
raw pose data and the KB matcher.

Design
------
The orchestrator is a single function with a module-level dispatch
table. Each entry in the table pairs an extractor instance with the
runtime kwargs that extractor needs beyond the standard
(pose_landmarks, checkpoints, handedness) trio. Currently only
`TempoExtractor` needs an extra kwarg (`fps`); everything else runs
on the standard trio.

At import time the module verifies that the union of every
extractor's `FEATURES` equals `schema.FEATURE_NAMES` exactly. Any
mismatch — a schema field with no producer, a producer of an unknown
name, or two extractors claiming the same feature — is a startup
error, not a silent NaN. This is deliberately loud: the
`hip_rotation_change_P7_to_P10` gap that motivated this whole
milestone was exactly that class of silent-bug, and we don't want
another.

Aggregation across swings is not this module's job. The caller
computes one `SwingFeatures` per swing via
`compute_swing_features`, then passes the list to
`schema.aggregate`.
"""

from __future__ import annotations

from typing import Any, Callable

from ..pose.extractor import PoseData
from .extractors.interpolated_p5 import InterpolatedP5Extractor
from .extractors.position import PositionExtractor
from .extractors.posture import PostureExtractor
from .extractors.rotation import RotationExtractor
from .extractors.tempo import TempoExtractor
from .extractors.wrists import WristExtractor
from .landmarks import Handedness
from .schema import FEATURE_NAMES, SwingFeatures


# Dispatch table: each entry pairs an extractor instance with a
# function that maps a PoseData into the extra kwargs that extractor
# needs. Extractors on the standard (landmarks, checkpoints,
# handedness) signature use an empty-dict mapping.
#
# When adding a new extractor: append (extractor, kwargs_fn) here.
_ExtraKwargsFn = Callable[[PoseData], dict[str, Any]]

_EXTRACTOR_DISPATCH: list[tuple[Any, _ExtraKwargsFn]] = [
    (WristExtractor(),          lambda pose: {}),
    (RotationExtractor(),       lambda pose: {}),
    (PostureExtractor(),        lambda pose: {}),
    (PositionExtractor(),       lambda pose: {}),
    (TempoExtractor(),          lambda pose: {"fps": pose.fps}),
    (InterpolatedP5Extractor(), lambda pose: {}),
]


def _validate_schema_coverage() -> None:
    """
    Assert union of every extractor's FEATURES equals FEATURE_NAMES
    from schema exactly.

    Fails loud on: missing producers, unknown feature names, or
    duplicate feature names across extractors.
    """
    produced: dict[str, str] = {}
    for extractor, _ in _EXTRACTOR_DISPATCH:
        cls_name = extractor.__class__.__name__
        for name in extractor.FEATURES:
            if name in produced:
                raise RuntimeError(
                    f"Feature {name!r} produced by both "
                    f"{produced[name]} and {cls_name}."
                )
            produced[name] = cls_name

    schema_set = set(FEATURE_NAMES)
    produced_set = set(produced.keys())

    missing = schema_set - produced_set
    if missing:
        raise RuntimeError(
            f"Schema fields with no producer: {sorted(missing)}."
        )

    extra = produced_set - schema_set
    if extra:
        raise RuntimeError(
            f"Extractor-produced features not in schema: {sorted(extra)}."
        )


_validate_schema_coverage()


def compute_swing_features(
    pose_data: PoseData,
    checkpoints: dict[str, int],
    handedness: Handedness = Handedness.RIGHT_HANDED,
) -> SwingFeatures:
    """
    Run every extractor on one swing and return a merged SwingFeatures.

    Parameters
    ----------
    pose_data:
        PoseData from `pose.extractor.load_pose` or `extract_pose`.
    checkpoints:
        Dict with keys "P1", "P4", "P7", "P10" and int frame indices.
        Must satisfy P1 < P4 < P7 < P10.
    handedness:
        Handedness.RIGHT_HANDED or LEFT_HANDED. Defaults to RH.

    Returns
    -------
    A SwingFeatures instance with every schema field populated
    (finite value or NaN — never missing).

    Raises
    ------
    ValueError:
        If required checkpoint keys are missing or ordering is
        violated. Extractors defend against degenerate input with
        NaN internally, but we fail fast here since a garbage
        ordering means every downstream value is unreliable.
    KeyError, TypeError:
        Propagated from schema construction if an extractor produces
        an unexpected feature set (caught at import time by
        `_validate_schema_coverage`, but re-raised at runtime if
        somehow the invariant is violated on this call).
    """
    required_keys = ("P1", "P4", "P7", "P10")
    missing = [k for k in required_keys if k not in checkpoints]
    if missing:
        raise ValueError(
            f"checkpoints missing required keys: {missing}. "
            f"Got: {sorted(checkpoints.keys())}"
        )

    p1, p4, p7, p10 = (checkpoints[k] for k in required_keys)
    if not (p1 < p4 < p7 < p10):
        raise ValueError(
            f"checkpoint ordering violated (need P1<P4<P7<P10): "
            f"P1={p1}, P4={p4}, P7={p7}, P10={p10}"
        )

    merged: dict[str, float] = {}
    for extractor, kwargs_fn in _EXTRACTOR_DISPATCH:
        extra_kwargs = kwargs_fn(pose_data)
        result = extractor.extract(
            pose_data.landmarks, checkpoints, handedness, **extra_kwargs,
        )
        # Sanity: each extractor returns exactly its declared FEATURES.
        # A mismatch here means an extractor is misbehaving at runtime
        # despite the import-time schema check.
        declared = set(extractor.FEATURES)
        returned = set(result.keys())
        if declared != returned:
            raise RuntimeError(
                f"{extractor.__class__.__name__} declared "
                f"{sorted(declared)} but returned {sorted(returned)}."
            )
        merged.update(result)

    return SwingFeatures(**merged)