# Phase 1 Notes — Pose Extraction and Segmentation

Completed end-to-end pose extraction and P1/P4/P7/P10 checkpoint
detection. The pipeline runs cleanly on 15 test swings spanning 27-120
fps and a mix of normal swings, intentional misses, and varied tempos.

## What was built

**`src/golf_diagnostic/pose/extractor.py`**

MediaPipe Pose extraction with NPZ caching. Returns a `PoseData`
dataclass containing landmarks of shape `(n_frames, 33, 4)` plus
video metadata (fps, resolution, frame count, detection rate).
Frames where pose detection fails are NaN-filled to keep the time
axis aligned to actual video frames.

**`src/golf_diagnostic/pose/visualizer.py`**

Renders annotated videos from extracted pose data, with optional
checkpoint banners. Lead-side limbs are drawn green, trail-side red,
to make left/right misidentification visually obvious. Drawing is
done with OpenCV directly rather than MediaPipe's drawing utilities,
so the visualizer is model-agnostic.

**`src/golf_diagnostic/segmentation/detector.py`**

Rule-based detection of P1, P4, P7, P10 from smoothed wrist-height
and wrist-velocity time series. The key abstraction is two
primitives — `_find_next_local_max` and `_find_next_local_min` —
which walk forward looking for the first local extremum that exceeds
a prominence threshold and is followed by sustained reversal. P4 and
P7 are detected via these primitives. P1 uses a "find the start of
sustained motion, then back up" heuristic. P10 uses a stable-rest
criterion after P7.

**`scripts/batch_segment.py`**

Runs the full pipeline (extract → cache → segment → render) over
every video in `data/raw/`. Prints a summary table and saves it to
`data/processed/segmentation_summary.txt`.

## Key technical decisions

**MediaPipe version pin.** `mediapipe==0.10.14`. Later versions
(0.10.21+) dropped the legacy `mp.solutions` API on some platforms,
which would break the extractor.

**NaN-fill instead of skip.** When MediaPipe fails to find a pose,
the extractor inserts a row of NaN rather than skipping the frame.
This keeps the time axis aligned to real video frames. Downstream
code interpolates NaN values during signal computation.

**Cache pose data to NPZ.** MediaPipe is the slow part of the
pipeline (~1-2 seconds per second of video). Every downstream
module loads from cache rather than re-running inference. Pose data
is recomputed only when forced via the `--force` flag.

**Trust iteration, not metadata.** `cv2.CAP_PROP_FRAME_COUNT` is
unreliable on phone video (observed: reports 111 frames on a clip
where only 99 frames actually decoded). The extractor iterates until
`cap.read()` returns false and counts actual reads.

**Local extrema with prominence filtering for P4 and P7.** Initial
implementation used global max for P4 and global min for P7. This
failed on clips where the follow-through reached higher than the top
of the backswing (e.g., swing_09: real P4 at frame 23, detected
frame 39 in the follow-through). The fix was structural: detect
each checkpoint as the *first* local extremum after the previous
checkpoint, with a prominence threshold (`EXTREMUM_PROMINENCE = 0.05`
normalized units) to reject noise and a sustain requirement
(`EXTREMUM_SUSTAIN_FRAMES = 3`) to confirm reversals.

**Color-coded skeleton overlay.** Lead and trail limbs are colored
differently in the visualizer so that left/right misassignment
would be visually obvious. None observed across the test dataset.

## Validation results

15 test swings spanning 27-120 fps:

- Pose detection: 100% on every clip
- Segmentation success (P1 < P4 < P7 < P10): 15/15
- P4 prominence-based confidence: 1.00 on all 15 clips
- P7 confidence: 0.51-0.74 range across all clips
- P4 and P7 detection visually verified correct on multiple swings

## Known limitations and deferrals

**P1 lands a few frames into the takeaway, not at true address.**
The detector picks the last quiet frame before sustained wrist
motion begins, but wrist motion is a lagging indicator — the
shoulders and club start moving a few frames before the wrists
register meaningful velocity. The consistent bias is ~3-5 frames
late across the dataset.

Impact on diagnosis: most setup features (spine angle, knee flex,
hand position, hip alignment, stance) are essentially unchanged
between true address and 3-5 frames into takeaway. The exception
is shoulder alignment, which changes measurably during early
takeaway — a swing with truly closed shoulders at address may
read as square if P1 captures a few frames of takeaway rotation.

Deferred fix: shoulder-rotation-based P1 detection. To be revisited
during Phase 2 if shoulder-alignment features look contaminated.

**P7 may have a small early bias.** Inferred from visual inspection
of banner edges across multiple clips: the detected impact frame may
sit ~2-3 frames before true impact on some swings. This is consistent
with how the local-min detection fires — wrists may reach near-bottom
slightly before clubhead reaches the ball. Not validated against
ground truth (no labeled frame data). Deferred to Phase 2 feature
evaluation.

**P10 confidence is low on short clips.** Several clips end shortly
after impact, before a stable settled-finish position is reached.
The detector falls back to the last frame in these cases. Not a
correctness issue, but a limitation on clip composition — for clean
P10 detection, clips should include 0.5-1 second of held finish.

**Frame rate variation.** Test dataset includes clips from 27-120
fps. The pipeline correctly handles fps via `cv2.CAP_PROP_FPS` and
all downstream metrics use real time (seconds), not frame indices.
Production data should target 60+ fps for reliable impact-frame
detection.

## Phase 2 entry conditions

- Pose extraction reliable on the test dataset
- Segmentation produces frame indices for all four checkpoints
- Cached pose data and segmentation results available for all 15
  test swings in `data/processed/`