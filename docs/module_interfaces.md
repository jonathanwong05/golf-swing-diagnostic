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

│   ├── orchestrator.py      # compute_swing_features(pose, checkpoints, handedness) -> SwingFeatures

│   └── extractors/

│       ├── wrists.py        # WristExtractor

│       ├── rotation.py      # RotationExtractor

│       ├── posture.py       # PostureExtractor

│       ├── position.py      # PositionExtractor

│       ├── tempo.py         # TempoExtractor

│       └── interpolated_p5.py  # InterpolatedP5Extractor

├── kb/

│   └── loader.py            # KB YAML → KnowledgeBase; Pydantic validation

├── diagnosis/

│   └── matcher.py           # (swings, aggregate, kb) → list[RankedCause]

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

**Status**: `aggregate()` is called by the matcher in
`src/golf_diagnostic/diagnosis/matcher.py`. Also used by KB audit
and sanity scripts.

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

**Features (7)**:
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

**Empirical baselines** (normal-swing means, 15-swing dataset,
`kb/baseline.yaml`):
- shoulder@P4: −0.702, shoulder@P7: −0.256
- hip@P4: −0.398, hip@P7: −0.178, hip@P10: +0.444

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
notes). Used across slice, pull, push, fat, thin, and shank causes.
`spine_angle_change_P1_to_P4` is the discriminator between early
extension (P1→P7 delta) and loss of posture (P1→P4 delta) in thin
contact.

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
- `hand_distance_from_body_at_P1` — used raw for shank
  standing_too_close cause (needs conservative thresholds due to 19%
  baseline CV) AND as stddev_gt for inconsistent_setup.
- `hand_distance_from_body_at_P7` — used for shank arms_disconnect.
- `ankle_displacement_at_P7`, `stance_width_at_P1`,
  `hip_displacement_P1_to_P7_target_axis` — retained for v2, no v1
  KB use.

---

### features/extractors/tempo.py

**Features (2)**: `tempo_ratio`, `total_swing_duration`

**Formulas**:
- `tempo_ratio` = (p4 − p1) / (p7 − p4). Unitless. Backswing frames
  divided by downswing frames.
- `total_swing_duration` = (p10 − p1) / fps. Seconds.

**Signature quirk**: `TempoExtractor.extract(...)` takes an optional
`fps: float | None = None` kwarg beyond the standard extractor
signature. If None, `total_swing_duration` returns NaN (frame count
still computed) — but in practice the orchestrator always passes fps
from `pose_data.fps`. Other extractors ignore the fps kwarg via the
orchestrator's dispatch table.

**Empirical baseline** (15 normal swings, `kb/baseline.yaml`):
- `tempo_ratio`: mean 2.01, stddev 0.35 — user's natural tempo sits
  below the 3:1 tour norm.
- `total_swing_duration`: mean 1.45s, stddev 0.335s.

**Validation status**: features are directly measured (no proxy).
Downgraded from validated to plausible confidence per phase2_notes
because slow-tempo demo (swing_26) failed to produce a slow swing
and rushed-transition demo (swing_27) underperformed.

---

### features/extractors/interpolated_p5.py

**Features (4)**:
- `lead_wrist_angle_at_P5_proxy` — interpolated frame midpoint of P4 and P7
- `trail_wrist_angle_at_P5_proxy` — interpolated frame midpoint
- `lead_arm_to_torso_angle_at_P5_proxy` — angle at midpoint
- `hand_path_proxy_at_P5_proxy` — change in hand-to-body distance P4→P5

**Frame choice**: values are measured at the interpolated midpoint
frame `(p4 + p7) // 2`, NOT the arithmetic mean of P4 and P7 feature
values. Option B from the design discussion — preserves what the
wrist actually did at midpoint rather than diluting with the
neutral P7 value.

**Wrist measurement side flip**: at P5, `lead_wrist_angle_at_P5_proxy`
is PRIMARY (baseline stddev 12.7°) and `trail_wrist_angle_at_P5_proxy`
is CORROBORATING (baseline stddev 20.0°) — the OPPOSITE of the P4/P7
convention. Motion jitter at mid-downswing exceeds visibility-limited
noise on the lead side. Documented in phase2_notes.

**Validation status**:
- `lead_wrist_angle_at_P5_proxy` — plausible (cupped demo validates
  direction; no casting demo)
- `trail_wrist_angle_at_P5_proxy` — weak (motion-noisy)
- `lead_arm_to_torso_angle_at_P5_proxy` — plausible (baseline clean;
  no shank demo)
- `hand_path_proxy_at_P5_proxy` — weak. All 15 normals had negative
  values (hands moving inward at P5). Over-the-top demo swing_20 was
  more negative than baseline, wrong direction — feature captures
  wrong phase of downswing for the OTT fault. Used only as a
  corroborator in shank cause 3.

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

## kb/loader.py

Loads and validates KB YAML files. First file in the `kb/` Python
package.

**Constants**
- `SUPPORTED_SYMPTOMS: frozenset[str]` — the 9 v1 symptoms: `slice`,
  `hook`, `pull`, `push`, `fat_contact`, `thin_contact`,
  `lack_of_distance`, `inconsistent_contact`, `shank`.

**Pydantic models**

```python
class Indicator(BaseModel):
    feature: str                              # must be in FEATURE_NAMES
    mode: Literal["raw", "zscore", "stddev_gt"]
    operator: Literal["gt", "lt", "gte", "lte", "abs_gt"]
    threshold: float
    confidence_weight: float                  # 0.0 to 1.0
    reasoning: str = ""

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
    indicators: list[Indicator]               # min 1
    fix: Fix
    feels: list[Feel]                         # min 1
    drills: list[Drill] = []
```

**BaselineEntry dataclass** (per-feature statistics from
`kb/baseline.yaml`):
```python
@dataclass(frozen=True)
class BaselineEntry:
    mean: float   # NaN if n == 0
    stddev: float # NaN if n < 2
    n: int
```

**KnowledgeBase container**:
```python
@dataclass(frozen=True)
class KnowledgeBase:
    causes_by_symptom: dict[str, list[Cause]]
    baseline: dict[str, BaselineEntry]

    def get_causes(self, symptom: str) -> list[Cause]
    def loaded_symptoms(self) -> list[str]
```

**Public function**
```python
load_kb(kb_dir: Path) -> KnowledgeBase
```

**Invariants / gotchas**
- Baseline must exist at `<kb_dir>/baseline.yaml`. Missing baseline
  → `FileNotFoundError`. Do not degrade gracefully; missing baseline
  is a broken repo state.
- Baseline must cover every feature in `FEATURE_NAMES`. Missing
  features → `ValueError`.
- Symptom filename stem must be in `SUPPORTED_SYMPTOMS`. A file like
  `kb/Slice.yaml` (wrong casing) or `kb/slicee.yaml` (typo) raises
  `ValueError`. Missing symptom files are OK — loader returns partial
  coverage during authoring.
- Every indicator's `feature` field is validated against
  `FEATURE_NAMES` at Pydantic parse time.
- `mode: zscore` indicators are cross-validated at load time against
  baseline: if the referenced feature has non-finite stddev or
  stddev < 1e-9, `ValueError`.
- `mode: stddev_gt` indicators must have non-negative threshold.
- Duplicate `cause_id` within a symptom file → `ValueError`.
- `KnowledgeBase.get_causes(symptom)` for an unloaded symptom returns
  `[]`; for an unsupported symptom raises `KeyError`.
- Loader ignores `baseline.yaml` when scanning `<kb_dir>` for symptom
  files.

---

## diagnosis/matcher.py

Matches user swings against KB causes. First file in the `diagnosis/`
package.

**Module constants**
- `CONSISTENCY_THRESHOLD = 0.60` — fraction of swings on which a
  per-swing indicator must fire to count as matched.
- `FALLBACK_SCORE_FLOOR = 0.5` — top cause must clear this to avoid
  fallback.

**Result types**
```python
@dataclass(frozen=True)
class MatchedIndicator:
    indicator: Indicator
    hit_count: int              # swings where indicator fired
    swing_count: int            # total swings evaluated
    representative_value: float # mean of hit values (per-swing)
                                # or the aggregate stddev (stddev_gt mode)

@dataclass(frozen=True)
class RankedCause:
    cause: Cause
    score: float                # sum of matched indicators' weights
    matched_indicators: list[MatchedIndicator]
```

**Public functions**
```python
match_symptom(
    symptom: str,
    swings: list[SwingFeatures],
    aggregate: AggregatedFeatures,
    kb: KnowledgeBase,
) -> list[RankedCause]
    # Returns all causes for the symptom sorted descending by score.
    # Ties preserved in KB author order (stable sort).
    # Empty list if the symptom has no loaded KB.
    # Raises ValueError if swings is empty.

should_fall_back(ranked: list[RankedCause]) -> bool
    # True if the empty list, no matched indicators, or
    # top score < FALLBACK_SCORE_FLOOR.
```

**Indicator evaluation semantics**
- `mode: raw` — evaluate condition on the per-swing feature value
  directly. NaN never matches. Per-swing → apply consistency filter.
- `mode: zscore` — evaluate condition on the z-score
  `(value - baseline.mean) / baseline.stddev`. Per-swing → apply
  consistency filter. Requires finite baseline stddev (guarded at
  load time; defensively rechecked at eval time).
- `mode: stddev_gt` — evaluate condition on the aggregate's
  cross-swing stddev of the feature. BYPASSES the consistency filter.
  NaN stddev (n<2 swings) never matches. `representative_value` is
  the aggregate stddev itself.

**Operator table** (module-level `_OPERATORS`):
`{"gt": op.gt, "lt": op.lt, "gte": op.ge, "lte": op.le,
"abs_gt": lambda x, t: abs(x) > t}`.

**Extending**
Adding a new operator or mode requires (1) updating the
`Indicator.operator` / `Indicator.mode` Literals in `kb/loader.py`,
(2) adding the branch in `_evaluate_per_swing` or `_evaluate_stddev`
in `matcher.py`, (3) documenting in this file.

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
    <feature_name>:
      direction: high | low
      known_weak: true            # optional
  deferred: true                  # optional; skip validation
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

## KB layout

kb/

├── baseline.yaml               # per-feature mean/stddev/n from normals

├── slice.yaml                  # per-symptom cause definitions

├── hook.yaml

├── pull.yaml

├── push.yaml

├── fat_contact.yaml

├── thin_contact.yaml

├── lack_of_distance.yaml

├── inconsistent_contact.yaml

└── shank.yaml

### `kb/baseline.yaml`

Flat dict keyed by feature name. One entry per feature in
`FEATURE_NAMES`. Regenerated by `scripts/regenerate_baseline.py`
from swings labeled `type: normal` in `data/labels.yaml`.

Header comment documents regeneration policy. Entry format:
```yaml
shoulder_rotation_proxy_at_P4:
  mean: -0.7023
  stddev: 0.0346
  n: 15
```

`mean: null` when `n: 0`. `stddev: null` when `n < 2`.

**Regeneration is a deliberate action, not a runtime side effect.**
Regenerating after refilming normals or changing extractors
implicitly retunes all `zscore`-mode KB thresholds. That's the
intended tradeoff; commit the diff explicitly.

Values are rounded to 4 decimals for reproducible byte-identical
output across runs.

### `kb/<symptom>.yaml`

List of causes at the top level. Each cause is a Pydantic-validated
`Cause` (see `kb/loader.py`). Priority is implicit in list order —
ties in matcher score are broken by YAML list order via stable sort.

Comment block at the top of each file documents:
- Symptom description
- V1 drops (which causes are missing and why)
- Any threshold philosophy specific to this file (e.g.,
  `inconsistent_contact.yaml` documents the "2× population baseline
  stddev" rule for stddev_gt indicators)

Every threshold and weight has a `reasoning` field on the indicator
explaining where the value came from. Convention:
- Cite baseline statistics from `baseline.yaml`
- Cite fault-demo evidence when validated
- Cite `causes_catalog.md` when reusing a shared cause across symptom
  files (the "consistency rule": same feature → same threshold →
  same weight across every symptom)
- Cite `phase2_notes.md` or `phase3_notes.md` when the choice
  reflects an empirical finding

---

## Scripts

### `scripts/batch_segment.py`
Runs the full Phase 1 pipeline over `data/raw/*.mov`. Pose data is
cached; pass `--force` to re-extract. Writes `segmentation_summary.txt`.
python scripts/batch_segment.py [--force]

### `scripts/regenerate_baseline.py`
Regenerates `kb/baseline.yaml` from swings labeled `type: normal` in
`data/labels.yaml`. Loads cached pose NPZs, parses checkpoints from
`segmentation_summary.txt`, runs `compute_swing_features` on each
swing, aggregates. Fails loud on missing pose cache or missing
checkpoint entry.
python scripts/regenerate_baseline.py

### `scripts/audit_kb_against_normals.py`
For each loaded symptom (or a specific one via `--symptom`),
evaluates every normal swing individually against the KB and
reports whether the fallback would trigger. False positives (fallback
did NOT trigger) surface threshold-tuning problems. Near misses
(fallback triggered but score > 0) show corroborator-only or
below-floor fires that are correct behavior.

The audit is a threshold pressure test, not an accuracy metric. See
phase3_notes.md for interpretation rules and persistent-anomaly
documentation (swing_11 spine change, swing_06 shoulder rotation,
swing_10 hand distance).
python scripts/audit_kb_against_normals.py [--symptom NAME]

### `scripts/test_matcher.py`
End-to-end matcher tests. Six test cases:
- Test A: 3 normal swings vs slice (expect fallback)
- Test B: swing_16 (cupped fault demo) vs slice (expect
  cupped_lead_wrist_at_top #1 at 1.40)
- Test C: swing_25 (short_backswing demo) vs lack_of_distance
  (expect insufficient_body_rotation #1 at 1.50)
- Test D: swing_22 (hanging_back demo) vs push (expect hanging_back
  at 0.50, just clears floor — validated with modest signal)
- Test E: 15 normals grouped vs inconsistent_contact (expect
  fallback — population stddev is the reference, 2×-baseline
  thresholds hold)
- Test F: 5 disparate fault demos vs inconsistent_contact (expect
  only inconsistent_top_of_backswing firing at 0.50)

Serves as regression check for matcher, loader, and KB threshold
integrity. If a threshold change or schema change breaks a validated
test, it surfaces here.
python scripts/test_matcher.py

### `scripts/test_kb_loader.py`
Sanity-checks the KB loader against whatever's currently in `kb/`.
Prints loaded symptoms with cause/indicator/feel counts.
python scripts/test_kb_loader.py

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

### `scripts/validate_features.py`
End-to-end regression check driven by `data/labels.yaml`. Runs the
orchestrator on every labeled swing and verifies fault demos produce
expected feature directions. See phase2_notes for validation-result
categories (validated / weak-signal / feature-intrinsic / demo-
execution-gap / structural-only).
python scripts/validate_features.py

---

## Environment

- Python 3.12.13
- Virtual env at `.venv`
- Package installed editable: `pip install -e .`
- Key pins: `mediapipe==0.10.14`, `pydantic`, `pyyaml`, `anthropic`
- Runs on CPU (no GPU needed for MediaPipe Pose)