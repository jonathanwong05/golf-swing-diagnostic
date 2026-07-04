# Module Interfaces

Cheat sheet of every public API in the codebase. Read this before
writing code that touches an existing module — do not guess at
signatures, constants, or file layouts.

Update this doc whenever a module's public surface changes.

---

## Package layout

src/golf_diagnostic/

├── pose/

│   ├── extractor.py         # video → PoseData; NPZ cache I/O

│   └── visualizer.py        # PoseData → annotated MP4

├── segmentation/

│   └── detector.py          # PoseData → SwingSegmentation (P1/P4/P7/P10)

├── features/

│   ├── landmarks.py         # named MediaPipe indices; Handedness enum;

│   │                        # lead()/trail() joint resolution

│   ├── primitives.py        # geometric toolkit (angles, distances,

│   │                        # midpoints, projections)

│   ├── schema.py            # SwingFeatures dataclass, FEATURE_NAMES,

│   │                        # AggregatedFeatures, aggregate()

│   └── extractors/

│       ├── wrists.py        # WristExtractor

│       ├── rotation.py      # RotationExtractor

│       ├── posture.py       # PostureExtractor

│       └── position.py      # PositionExtractor

├── diagnosis/               # Phase 3+ (empty)

├── kb/                      # Phase 3+ (empty)

└── api/                     # Phase 5+ (empty)

All `__init__.py` files are empty. Imports must be fully qualified
(e.g. `from golf_diagnostic.features.extractors.wrists import WristExtractor`).

---

## pose/extractor.py

**Constants**
- `N_LANDMARKS = 33` — MediaPipe pose landmark count
- `N_COORDS = 4` — (x, y, z, visibility) per landmark

**PoseData dataclass**
```python
@dataclass
class PoseData:
    landmarks: np.ndarray  # shape (n_frames, 33, 4); NaN where detection failed
    fps: float
    width: int
    height: int
    n_frames: int          # actual frames read, not metadata count
    detection_rate: float  # fraction of frames with successful detection

    @property
    def duration_seconds(self) -> float
```

**Public functions**
```python
extract_pose(video_path: Path | str) -> PoseData
save_pose(pose_data: PoseData, output_path: Path | str) -> None
load_pose(input_path: Path | str) -> PoseData
```

**Invariants / gotchas**
- `landmarks[i, j, :]` is `[x, y, z, visibility]`. x and y are
  normalized to [0, 1] against image width/height.
- Frames where MediaPipe failed are NaN-filled — the time axis is
  aligned to real video frames, no dropped frames.
- `n_frames` reflects actual `cap.read()` iterations, NOT
  `cv2.CAP_PROP_FRAME_COUNT` (which is unreliable on phone video).
- `save_pose` uses `np.savez_compressed`; NPZ keys are
  `landmarks`, `fps`, `width`, `height`, `n_frames`, `detection_rate`.
- MediaPipe version pinned to `0.10.14` — later versions dropped the
  `mp.solutions` API used here.

---

## pose/visualizer.py

**Public functions**
```python
render_pose_video(
    video_path: Path | str,
    pose_data: PoseData,
    output_path: Path | str,
) -> None

render_segmented_pose_video(
    video_path: Path | str,
    pose_data: PoseData,
    segmentation: SwingSegmentation,
    output_path: Path | str,
) -> None
```

**Notes**
- Lead-side limbs drawn green, trail-side red, torso crossbars white.
  Colors are hardcoded to physical left/right (not lead/trail), so
  overlay reads left-handed for LH golfers. Intentional — visual
  debugging tool.
- Checkpoint banners persist ±5 frames around each detected checkpoint.
- All drawing is via OpenCV; MediaPipe drawing utilities are not used.

---

## segmentation/detector.py

**SwingSegmentation dataclass**
```python
@dataclass
class SwingSegmentation:
    p1: int
    p4: int
    p7: int
    p10: int
    p1_confidence: float
    p4_confidence: float
    p7_confidence: float
    p10_confidence: float
    success: bool         # False if ordering p1 < p4 < p7 < p10 violated
    failure_reason: str   # empty string if success
```

**Public function**
```python
segment_swing(pose_data: PoseData) -> SwingSegmentation
```

**Invariants / gotchas**
- Returns success=False (all indices = 0) if `n_frames < 10`.
- Confidence scores are heuristic, roughly [0.0, 1.0]. Empirical
  ranges on the 15-swing normal dataset: P4=1.00 always, P7=0.51-0.74,
  P1 & P10 highly variable.
- P1 lands ~3-5 frames into the takeaway, not at true address.
  Setup features tolerate this bias.
- Extremum detection uses `_find_next_local_max` / `_find_next_local_min`
  with `EXTREMUM_PROMINENCE=0.05` and `EXTREMUM_SUSTAIN_FRAMES=3`.
  Do not revert to global-max heuristics — they fail on swings with
  high follow-throughs.

**How checkpoints are consumed downstream**
- Feature extractors take `checkpoints: dict[str, int]` with keys
  `"P1"`, `"P4"`, `"P7"`, `"P10"` — a plain dict, not a
  SwingSegmentation object. Callers build this dict themselves.
- Test scripts parse checkpoints from `segmentation_summary.txt`
  via regex (see "Data layout" below).

---

## features/landmarks.py

**Handedness enum**
```python
class Handedness(Enum):
    RIGHT_HANDED = "right"  # lead = left side of body
    LEFT_HANDED = "left"    # lead = right side of body
```

**Landmark index constants** (subset of the 33)
- Head: `NOSE = 0`
- Upper body: `LEFT_SHOULDER`, `RIGHT_SHOULDER`, `LEFT_ELBOW`,
  `RIGHT_ELBOW`, `LEFT_WRIST`, `RIGHT_WRIST`, `LEFT_PINKY`,
  `RIGHT_PINKY`, `LEFT_INDEX`, `RIGHT_INDEX`, `LEFT_THUMB`, `RIGHT_THUMB`
- Lower body: `LEFT_HIP`, `RIGHT_HIP`, `LEFT_KNEE`, `RIGHT_KNEE`,
  `LEFT_ANKLE`, `RIGHT_ANKLE`, `LEFT_HEEL`, `RIGHT_HEEL`,
  `LEFT_FOOT_INDEX`, `RIGHT_FOOT_INDEX`

**Channel constants** (indexing the last axis of `pose_landmarks`)
- `X = 0`, `Y = 1`, `Z = 2`, `VISIBILITY = 3`

**Handedness-aware joint resolvers**
```python
lead(joint: str, handedness: Handedness = Handedness.RIGHT_HANDED) -> int
trail(joint: str, handedness: Handedness = Handedness.RIGHT_HANDED) -> int
```

**Valid joint name strings** (lowercase, singular):
`"shoulder"`, `"elbow"`, `"wrist"`, `"pinky"`, `"index"`, `"thumb"`,
`"hip"`, `"knee"`, `"ankle"`, `"heel"`, `"foot_index"`.

Passing an unknown joint name raises `KeyError`.

**Usage pattern**
```python
lead_wrist_idx = lead("wrist", Handedness.RIGHT_HANDED)  # -> 15
row = pose_landmarks[frame, lead_wrist_idx]  # [x, y, z, visibility]
```

Always resolve via `lead()`/`trail()` in extractors. Do not
hardcode `LEFT_WRIST` / `RIGHT_WRIST` — it breaks left-handed support.

---

## features/primitives.py

Geometric toolkit. All functions take numpy arrays; length-4
landmark rows are accepted (z and visibility are sliced off
internally when only x, y are needed).

```python
distance(a, b) -> float
    # Euclidean 2D distance.

midpoint(a, b) -> np.ndarray  # shape (2,)
    # Point halfway between a and b.

angle_at_joint(a, b, c) -> float
    # Interior angle in DEGREES at point b, formed by b->a and b->c.
    # Returns NaN on degenerate geometry.

signed_angle_2d(v1, v2) -> float
    # Signed angle in degrees from v1 to v2.
    # Positive = CCW in screen coords (which is CW in world, since
    # y increases downward). Sign is consistent across the codebase.

horizontal_displacement(point, reference) -> float
    # Signed image-x delta (point.x - reference.x).
    # Positive = right in image.

vertical_displacement(point, reference) -> float
    # Signed vertical delta, sign-flipped so "up in world" is positive.
    # Formula: reference.y - point.y.

displacement_toward_lead_side(point, reference, lead_foot, trail_foot) -> float
    # Signed displacement of (point - reference), projected onto the
    # trail_foot -> lead_foot axis. Positive = lead-side direction.
    # Camera-agnostic axis resolution.

is_valid(*points) -> bool
    # True if every point has finite x and y (NaN check).

low_visibility(*points, threshold=0.5) -> bool
    # True if any landmark has visibility below threshold.
    # Silently False for points without a visibility channel.
```

**Conventions**
- Angles in degrees, not radians.
- y increases downward (image coords). Helpers wrap this so
  extractors don't have to.
- NaN propagates: any NaN input → NaN output.

---

## features/schema.py

**FEATURE_NAMES** — canonical tuple of KB-facing feature name strings.
The single source of truth for what features exist. Currently **36
entries** after Phase 2 drops (weight distribution, setup alignment
lines, grip strength — see `docs/measurement_visibility_decisions.md`
for the "invisible axis" principle).

**SwingFeatures dataclass**
- One `float` field per name in `FEATURE_NAMES`.
- NaN means "feature unavailable" — distinct from "feature is zero."
- Methods:
```python
  swing.to_dict() -> dict[str, float]
  swing.get(name: str) -> float  # raises KeyError on unknown name
```

**AggregatedFeatures dataclass**
- Cross-swing aggregates. Fields:
```python
  n_swings: int
  _values: dict[str, dict[str, float]]  # {feature: {mean, stddev, range}}
```
- Method:
```python
  agg.get(name: str, kind: Literal["mean", "stddev", "range"] = "mean") -> float
  agg.to_dict() -> dict[str, dict[str, float]]
```

**aggregate() function**
```python
aggregate(swings: list[SwingFeatures]) -> AggregatedFeatures
```
- NaN values are skipped per feature.
- If 0 finite values: mean/stddev/range all NaN.
- If 1 finite value: mean is that value, stddev/range NaN.
- Raises `ValueError` on empty input.

**Status**: `aggregate()` is built but nothing calls it yet. Reserved
for Phase 3 (KB matching) and Phase 4 (LLM prompt construction).

---

## features/extractors/ — common contract

Every extractor follows this pattern:

```python
class SomethingExtractor:
    FEATURES: tuple[str, ...]  # names it produces

    def extract(
        self,
        pose_landmarks: np.ndarray,           # shape (n_frames, 33, 4)
        checkpoints: dict[str, int],          # keys: "P1", "P4", "P7", "P10"
        handedness: Handedness = Handedness.RIGHT_HANDED,
    ) -> dict[str, float]:
        ...
```

**Return contract**
- Returned dict keys == `FEATURES` exactly (no extras, no missing).
- Missing/degenerate geometry → NaN, never a fake zero.
- Extractors do not import from each other or from schema — they are
  independent producers.

**Consuming multiple extractors** — see `orchestrator.py`. The
public function `compute_swing_features(pose_data, checkpoints,
handedness) -> SwingFeatures` calls every extractor with the kwargs
it needs (via a module-level dispatch table) and merges results
into a single `SwingFeatures`. Feature-name disjointness and
schema coverage are asserted at import time, so a mismatch between
`schema.FEATURE_NAMES` and the union of extractor `FEATURES` fails
loud rather than silently.

---

### features/extractors/wrists.py

**Features (6)**: `{lead,trail}_wrist_angle_at_{P1,P4,P7}`

**Signed convention**: forearm-to-hand vector angle.
Positive = cupped (extended), negative = bowed (flexed), zero = neutral.
Consistent across lead and trail sides.

**Landmarks used**: elbow, wrist, index (per side, per checkpoint).

**Validation status**: P4 wrist highly reliable (~52° cupped-vs-bowed
separation on fault demos). P7 wrist unreliable due to motion jitter
at 60fps — computed and stored anyway; KB will downweight. Do not
attempt to fix P7 at 60fps.

---

### features/extractors/rotation.py

**Features (6)**:
- `shoulder_rotation_proxy_at_{P4, P7}`
- `hip_rotation_proxy_at_{P4, P7, P10}`
- `hip_rotation_change_P7_to_P10` (delta: P10 minus P7)

**Formula**: signed image-x separation of paired landmarks
(trail.x − lead.x), normalized by ankle-to-hip vertical distance at P1.
Unitless ratio.

**Sign convention**:
- Negative = rotated in backswing direction (typical at P4)
- ~0 = shoulders/hips roughly parallel to target line
- Positive = rotated in follow-through direction (typical at P10)

**Empirical baselines** (normal-swing means, 15-swing dataset):
- shoulder@P4: −0.70, shoulder@P7: −0.26
- hip@P4: −0.40, hip@P7: −0.18, hip@P10: +0.44

**Constant**: `_MIN_REFERENCE_LENGTH = 0.05` — features return NaN if
ankle-to-hip vertical falls below this at P1.

**Do not revert** to horizontal shoulder-separation normalization
(catastrophic on parallel-to-camera P1 baselines) or ankle-to-ankle
horizontal (same failure mode, smaller).

**Delta feature note**: `hip_rotation_change_P7_to_P10` is the
extractor's one delta. Computed as `hip_rotation_proxy_at_P10 −
hip_rotation_proxy_at_P7`. Small or negative values indicate body
stall through impact (hook cause 4). Matches the posture extractor's
delta pattern.

---

### features/extractors/posture.py

**Features (9)**:
- `spine_angle_at_{P1, P4, P7}` — angle from vertical, unsigned, degrees
- `knee_flex_{lead, trail}_at_P1` — interior angle hip-knee-ankle
- `lead_elbow_angle_at_P4` — interior angle shoulder-elbow-wrist
- `lead_arm_angle_at_P7` — interior angle shoulder-elbow-wrist
- `spine_angle_change_P1_to_{P4, P7}` — deltas (P4/P7 minus P1)

**Sign conventions**:
- Spine angle: 0 = perfectly upright, larger = more forward tilt
- Interior angles: 180 = straight, smaller = more flexed/bent
- Deltas: positive = spine bent more forward, negative = straightened

**Why deltas exist**: absolute spine-angle values carry a session-level
offset (address posture varies day-to-day). The delta cancels it.
Consider this pattern for future extractors where absolute values
may drift across sessions.

**Diagnostic role of the deltas**:
`spine_angle_change_P1_to_P7` is the PRIMARY early-extension indicator
in the v1 KB. It took over that role from `hip_vertical_change_P1_to_P7`
(which is confounded by natural hip rotation — see position extractor
notes). Used across slice, push, fat, thin, and shank causes.

---

### features/extractors/position.py

**Features (9)**:
- `head_displacement_P1_to_P4` — target-axis only
- `head_displacement_P1_to_P7_target_axis` — target-axis component
- `head_vertical_change_P1_to_P7` — image-y component, raised=+
- `hip_displacement_P1_to_P7_target_axis` — target-axis (lateral slide)
- `hip_vertical_change_P1_to_P7` — image-y (CORROBORATING, not primary)
- `hand_distance_from_body_at_{P1, P7}` — perpendicular to torso axis
- `stance_width_at_P1` — normalized ankle separation
- `ankle_displacement_at_P7` — mid-ankle vertical change (raised=+)

**Normalization**: all features divided by ankle-to-hip vertical at P1.
Same reference as rotation extractor.

**Target axis**: unit vector from trail-ankle to lead-ankle at P1,
resolved per-swing. Displacements projected via dot product.

**Invariant**: if either ankle at P1 fails visibility, all
target-axis-projected features return NaN; vertical features can
still be computed.

**Constant**: `_MIN_REFERENCE_LENGTH = 0.05` (same as rotation).

**Diagnostic role**:
- `head_displacement_P1_to_P7_target_axis` — VALIDATED primary indicator
  for hanging back (z=−1.24 on swing_22 demo)
- `head_displacement_P1_to_P4` — WEAK primary indicator for reverse
  pivot (fires only on extreme cases; swing_24 demo failed direction)
- `hip_vertical_change_P1_to_P7` — CORROBORATING for early extension
  only. Confounded by natural hip rotation; do not treat as primary.
- `hand_distance_from_body_at_P7`, `ankle_displacement_at_P7`,
  `stance_width_at_P1` — noisy from down-the-line; KB downweights.

---

## Extractors NOT built (and why)

Three extractors from the original Phase 2 plan were dropped after
empirical investigation. See `docs/measurement_visibility_decisions.md`
for the "invisible axis" principle that governs these drops.

- **weight extractor** — attempted, produced ~1.0 constants across
  all swings and fault demos. The target axis in down-the-line view
  IS the camera axis, so projections onto it are numerical noise.
  Files not present.
- **setup_alignment extractor** — attempted for shoulder/hip lines,
  produced ±90° values with sd=60°+ (sign-flipping around a foot-line
  reference that is itself along the camera axis). Grip strength was
  never attempted (three stacked failure modes). Files not present.

Consequence for the schema: 6 features removed (weight ×3, alignment
×2, grip ×1). Field count 42 → 36. KB causes affected: reverse pivot
loses primary (falls back to head_displacement), hanging back keeps
primary via head_target_axis, early extension shifts to
spine_angle_change_P1_to_P7. Five causes dropped from v1: weak grip,
strong grip, aim left, aim right, no ground use.

---

## features/orchestrator.py

**Public function**
```python
compute_swing_features(
    pose_data: PoseData,
    checkpoints: dict[str, int],
    handedness: Handedness = Handedness.RIGHT_HANDED,
) -> SwingFeatures
```

**Invariants**
- Raises `ValueError` if any of `"P1"`, `"P4"`, `"P7"`, `"P10"` are
  missing from `checkpoints`, or if ordering `P1 < P4 < P7 < P10` is
  violated.
- At import time, asserts that `∪ extractor.FEATURES == FEATURE_NAMES`
  exactly. A mismatch (missing producer, unknown feature name,
  duplicate producer) raises `RuntimeError` on import.
- Returned `SwingFeatures` has every schema field populated —
  finite or NaN, never missing.

**Extending**
Add a new extractor to the module-level `_EXTRACTOR_DISPATCH` list.
Each entry is `(extractor_instance, lambda pose: {...extra kwargs})`.
Standard extractors use `lambda pose: {}`. If the extractor's
`FEATURES` don't reconcile with `FEATURE_NAMES`, import will fail.

---

## Data layout

data/

├── raw/

│   └── swing_NN.mov               # source videos, N=01..30+

├── processed/

│   ├── swing_NN_pose.npz          # cached pose data

│   ├── swing_NN_segmented.mp4     # annotated video with banners

│   ├── swing_NN_pose.mp4          # (older; annotated without banners)

│   └── segmentation_summary.txt   # per-swing checkpoint table

├── labels.yaml                    # per-swing intent labels

└── samples/                       # (empty; reserved)

### `data/processed/*_pose.npz`

NPZ keys: `landmarks`, `fps`, `width`, `height`, `n_frames`,
`detection_rate`. Load via `pose.extractor.load_pose(path)` — do NOT
`np.load` directly in new code (breaks abstraction).

### `data/processed/segmentation_summary.txt`

One line per swing. Format:
swing_NN    frames=NNN  fps=NN.NN  detect=NNN.N%  P1= NN(0.NN)  P4= NN(0.NN)  P7= NN(0.NN)  P10= NN(0.NN)  OK

**Regex for parsing** (used by all test scripts):
```python
pattern = re.compile(
    r"(swing_\d+).*?P1=\s*(\d+).*?P4=\s*(\d+).*?P7=\s*(\d+).*?P10=\s*(\d+)"
)
```

The `(0.NN)` values after each checkpoint are confidences, not part
of the frame index.

### `data/labels.yaml`

Per-swing intent labels for validation. Schema:
```yaml
swing_NN:
  type: "normal" | "fault_demo"
  intended_fault: <snake_case>    # fault_demo only
  expected_features:              # fault_demo only
    <feature_name>: <description>
  notes: <free text>
```

**Important**: labels.yaml contains entries for all swings currently
in the dataset. Normal swings 01-15, fault demos 16-34. All swings
assumed right-handed; there is no `handedness` field.

Load pattern:
```python
with open("data/labels.yaml") as f:
    labels = yaml.safe_load(f)
normal_ids = [sid for sid, meta in labels.items() if meta.get("type") == "normal"]
```

---

## Scripts

### `scripts/batch_segment.py`
Runs the full Phase 1 pipeline over `data/raw/*.mov`. Pose data is
cached; pass `--force` to re-extract. Writes `segmentation_summary.txt`.
python scripts/batch_segment.py [--force]

### `scripts/test_<extractor>_extractor.py`
Sanity script per extractor. Standard pattern:
1. Parse checkpoints from `segmentation_summary.txt` via regex
2. Load pose via `load_pose(POSE_DIR / f"{swing_id}_pose.npz")`
3. Run extractor on normal swings → baseline distribution
4. Run extractor on fault-demo swings → z-scores vs. baseline
5. NaN counts and structural checks

### `scripts/test_<module>.py`
Unit-ish tests for individual modules (primitives, schema,
segmentation, visualizer). Not pytest-based — plain `python
scripts/test_foo.py` and read output.

---

## Environment

- Python 3.12.13
- Virtual env at `.venv`
- Package installed editable: `pip install -e .`
- Key pins: `mediapipe==0.10.14`
- Runs on CPU (no GPU needed for MediaPipe Pose)
