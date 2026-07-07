"""
End-to-end analysis pipeline.

Given N video paths, a symptom, and a loaded KB, produces a
DiagnosticOutput. This is the module that Phase 5's FastAPI route
will call — everything above this line is upload / temp-file /
session management; everything below this module is pipeline
internals.

Composition, not new logic:
    extract_pose      → PoseData          (with npz cache)
    segment_swing     → SwingSegmentation (P1/P4/P7/P10)
    compute_swing_features
                      → SwingFeatures     (per swing)
    aggregate         → AggregatedFeatures (cross-swing)
    match_symptom     → list[RankedCause] (ranked causes)
    generate_diagnosis→ DiagnosticOutput  (LLM output)

Public API:
    analyze_swings(video_paths, symptom, kb, *, ...) -> AnalysisResult

The KB is passed in rather than loaded here. In Phase 5 the API
loads the KB once at startup and injects it into every request;
tests load it once per run. Same pattern as generate_diagnosis
accepting a client.

Failure model: raises on any per-swing failure (missing file,
segmentation failure, pose extraction failure). No graceful skipping
in v1. Phase 5 can add per-video tolerance ("swing 3 of 4 failed,
using the other 3") once real user data shows the need.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from golf_diagnostic.diagnosis.llm_client import generate_diagnosis
from golf_diagnostic.diagnosis.matcher import RankedCause, match_symptom
from golf_diagnostic.diagnosis.output_schema import DiagnosticOutput
from golf_diagnostic.features.landmarks import Handedness
from golf_diagnostic.features.orchestrator import compute_swing_features
from golf_diagnostic.features.schema import FEATURE_NAMES, aggregate
from golf_diagnostic.kb.loader import SUPPORTED_SYMPTOMS, KnowledgeBase
from golf_diagnostic.pose.extractor import (
    extract_pose,
    load_pose,
    save_pose,
)
from golf_diagnostic.pose.visualizer import render_segmented_pose_video
from golf_diagnostic.segmentation.detector import (
    SwingSegmentation,
    segment_swing,
)


# ---------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class AnalysisResult:
    """
    What analyze_swings returns.

    - diagnosis: the LLM-produced coaching output. This is the main
      product; the frontend renders it directly.
    - annotated_video_paths: paths to the P1/P4/P7/P10-annotated MP4s,
      one per input video, in the same order. Empty list when
      annotated_output_dir was None (which is the case for pipeline
      tests that don't need the videos rendered).
    - ranked_causes: the matcher's ranked output for the reported
      symptom. Not needed by the frontend, but useful for debug
      dashboards and for logging/observability in Phase 5.
    """

    diagnosis: DiagnosticOutput
    annotated_video_paths: list[Path]
    ranked_causes: list[RankedCause]


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _log(msg: str, verbose: bool) -> None:
    if verbose:
        print(f"[pipeline] {msg}", file=sys.stderr)


def _seg_to_checkpoints(seg: SwingSegmentation) -> dict[str, int]:
    """Convert SwingSegmentation to the dict shape orchestrator expects."""
    return {"P1": seg.p1, "P4": seg.p4, "P7": seg.p7, "P10": seg.p10}


def _validate_inputs(
    video_paths: list[Path],
    symptom: str,
    kb: KnowledgeBase,
) -> None:
    """Fail fast on obviously invalid inputs before any work is done."""
    if not video_paths:
        raise ValueError("video_paths is empty; at least one video is required.")

    if symptom not in SUPPORTED_SYMPTOMS:
        raise ValueError(
            f"symptom {symptom!r} is not supported. Must be one of "
            f"{sorted(SUPPORTED_SYMPTOMS)}."
        )

    if not kb.get_causes(symptom):
        raise ValueError(
            f"KB has no loaded causes for symptom {symptom!r}. Check "
            f"that kb/{symptom}.yaml exists and loaded cleanly."
        )

    missing = [p for p in video_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"Video file(s) not found: {[str(p) for p in missing]}"
        )


# ---------------------------------------------------------------------
# Per-video processing
# ---------------------------------------------------------------------


def _process_one_swing(
    video_path: Path,
    handedness: Handedness,
    cache_dir: Path,
    annotated_output_dir: Path | None,
    force_extract: bool,
    verbose: bool,
    index: int,
    total: int,
):
    """
    Run the pose → segmentation → features chain for one swing.

    Returns (SwingFeatures, annotated_output_path_or_None).
    """
    _log(f"[{index}/{total}] {video_path.name}: starting", verbose)

    # --- pose (with npz cache) ---
    cache_path = cache_dir / f"{video_path.stem}_pose.npz"
    if cache_path.exists() and not force_extract:
        _log(f"[{index}/{total}]   loading cached pose from {cache_path.name}", verbose)
        pose_data = load_pose(cache_path)
    else:
        _log(f"[{index}/{total}]   extracting pose from video (MediaPipe)…", verbose)
        pose_data = extract_pose(video_path)
        save_pose(pose_data, cache_path)
        _log(f"[{index}/{total}]   pose cached to {cache_path.name}", verbose)

    _log(
        f"[{index}/{total}]   pose: fps={pose_data.fps:.1f} "
        f"frames={pose_data.n_frames} detection={pose_data.detection_rate:.1%}",
        verbose,
    )

    # --- segmentation ---
    seg = segment_swing(pose_data)
    if not seg.success:
        raise ValueError(
            f"Segmentation failed for {video_path.name}: {seg.failure_reason}"
        )
    _log(
        f"[{index}/{total}]   checkpoints: "
        f"P1={seg.p1}({seg.p1_confidence:.2f}) "
        f"P4={seg.p4}({seg.p4_confidence:.2f}) "
        f"P7={seg.p7}({seg.p7_confidence:.2f}) "
        f"P10={seg.p10}({seg.p10_confidence:.2f})",
        verbose,
    )

    # --- features ---
    checkpoints = _seg_to_checkpoints(seg)
    features = compute_swing_features(pose_data, checkpoints, handedness)
    nan_count = sum(1 for v in features.to_dict().values() if not math.isfinite(v))
    _log(
        f"[{index}/{total}]   features: {len(FEATURE_NAMES) - nan_count}/"
        f"{len(FEATURE_NAMES)} finite ({nan_count} NaN)",
        verbose,
    )

    # --- optional annotated video ---
    annotated_path: Path | None = None
    if annotated_output_dir is not None:
        annotated_path = annotated_output_dir / f"{video_path.stem}_annotated.mp4"
        _log(f"[{index}/{total}]   rendering annotated → {annotated_path.name}", verbose)
        render_segmented_pose_video(video_path, pose_data, seg, annotated_path)

    return features, annotated_path


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def analyze_swings(
    video_paths: list[Path],
    symptom: str,
    kb: KnowledgeBase,
    *,
    user_context: str = "",
    handedness: Handedness = Handedness.RIGHT_HANDED,
    cache_dir: Path = Path("data/processed"),
    annotated_output_dir: Path | None = None,
    force_extract: bool = False,
    client: Anthropic | None = None,
    verbose: bool = False,
) -> AnalysisResult:
    """
    Full end-to-end analysis. Composes pose extraction, segmentation,
    feature computation, aggregation, matching, and LLM diagnosis.

    Parameters
    ----------
    video_paths
        Paths to the user's uploaded swing videos. Must be non-empty.
        The caller (Phase 5 API) is responsible for coercing uploaded
        bytes into files and passing their paths here.
    symptom
        User-reported symptom. Must be one of the 9 KB symptoms.
    kb
        Loaded KnowledgeBase. Passed in so callers can share one
        instance across requests. Load once with kb.loader.load_kb().
    user_context
        Optional free-text context from the user. Forwarded to
        generate_diagnosis.
    handedness
        Right-handed by default. All v1 test data is right-handed;
        Phase 5 can add a UI toggle.
    cache_dir
        Where pose NPZ files live. Default is the repo-level
        data/processed convention. In production Phase 5 will pass a
        per-session temp dir.
    annotated_output_dir
        If set, renders P1/P4/P7/P10-annotated MP4s to this dir and
        returns the paths in AnalysisResult.annotated_video_paths.
        If None, no rendering (faster; the return list is empty).
    force_extract
        If True, ignore the pose cache and re-extract from video.
        Useful when pose extractor code has changed.
    client
        Injectable Anthropic client. Defaults to Anthropic() which
        reads ANTHROPIC_API_KEY from env.
    verbose
        If True, log per-stage progress to stderr. Recommended for
        pipeline tests; silent by default.

    Returns
    -------
    AnalysisResult with diagnosis, annotated_video_paths, and
    ranked_causes.

    Raises
    ------
    ValueError
        On empty video_paths, unsupported symptom, unloaded KB
        symptom, or segmentation failure on any swing.
    FileNotFoundError
        If any video path does not exist.
    DiagnosisValidationError
        If the LLM output fails validation twice.
    anthropic.*
        API-level errors propagate.
    """
    _validate_inputs(video_paths, symptom, kb)

    # Fail-fast client init: if ANTHROPIC_API_KEY is missing, we want
    # to know before running pose extraction (which takes seconds).
    client = client or Anthropic()

    cache_dir.mkdir(parents=True, exist_ok=True)
    if annotated_output_dir is not None:
        annotated_output_dir.mkdir(parents=True, exist_ok=True)

    _log(
        f"analyzing {len(video_paths)} swing(s) for symptom={symptom!r}; "
        f"cache_dir={cache_dir} "
        f"annotated_output_dir={annotated_output_dir}",
        verbose,
    )

    # --- per-swing processing ---
    per_swing_features = []
    annotated_paths: list[Path] = []
    total = len(video_paths)

    for i, path in enumerate(video_paths, start=1):
        features, annotated = _process_one_swing(
            video_path=path,
            handedness=handedness,
            cache_dir=cache_dir,
            annotated_output_dir=annotated_output_dir,
            force_extract=force_extract,
            verbose=verbose,
            index=i,
            total=total,
        )
        per_swing_features.append(features)
        if annotated is not None:
            annotated_paths.append(annotated)

    # --- cross-swing aggregation ---
    agg = aggregate(per_swing_features)
    _log(f"aggregated features across {agg.n_swings} swing(s)", verbose)

    # --- KB matching ---
    ranked = match_symptom(symptom, per_swing_features, agg, kb)
    if ranked:
        top = ranked[0]
        _log(
            f"matcher: {len(ranked)} ranked cause(s); top = "
            f"{top.cause.cause_id!r} at score {top.score:.2f}",
            verbose,
        )
    else:
        _log("matcher: 0 ranked causes (KB returned empty list)", verbose)

    # --- LLM diagnosis ---
    diagnosis = generate_diagnosis(
        symptom=symptom,
        ranked=ranked,
        kb=kb,
        n_swings=len(per_swing_features),
        user_context=user_context,
        client=client,
        verbose=verbose,
    )

    return AnalysisResult(
        diagnosis=diagnosis,
        annotated_video_paths=annotated_paths,
        ranked_causes=ranked,
    )