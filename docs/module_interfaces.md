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

│   ├── matcher.py           # (swings, aggregate, kb) → list[RankedCause]

│   ├── output_schema.py     # DiagnosticOutput Pydantic model; validate_against_kb()

│   ├── prompt.py            # build_prompt() → PromptPayload (system, messages, tools)

│   └── llm_client.py        # generate_diagnosis() → DiagnosticOutput

├── pipeline.py              # analyze_swings() — full end-to-end orchestration

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

match_general(
    swings: list[SwingFeatures],
    aggregate: AggregatedFeatures,
    kb: KnowledgeBase,
) -> list[RankedCause]
    # Symptom-agnostic ranking. Pools unique causes across every
    # loaded symptom KB via collect_unique_causes, scores each
    # against the user's swings, returns descending by score.
    # Same scoring semantics as match_symptom (consistency filter
    # for per-swing indicators, bypass for stddev_gt).
    # Raises ValueError if swings is empty or if the KB fails the
    # diagnostic-identity check (see collect_unique_causes).

collect_unique_causes(kb: KnowledgeBase) -> list[Cause]
    # Deduplicates causes by cause_id across all loaded symptom KBs.
    # For shared cause_ids: enforces byte-identical diagnostic
    # content (indicators, fix, category) across every host file
    # via _assert_diagnostic_identity; pools coaching content
    # (feels, drills) as union with first-occurrence order.
    # Raises ValueError on diagnostic-content divergence — this is
    # a broken-KB error, not a user error.

should_fall_back(ranked: list[RankedCause]) -> bool
    # True if the empty list, no matched indicators, or
    # top score < FALLBACK_SCORE_FLOOR.
    # Mode-neutral: used identically for symptom and general paths.
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

**Diagnostic-identity check** (`_assert_diagnostic_identity`)
compares indicators via `_indicators_matcher_equal`, which
DELIBERATELY excludes the `Indicator.reasoning` field. Reasoning is
per-file authoring documentation — the matcher never reads it, the
LLM never sees it — and it legitimately varies across symptom files
for the same shared cause. Comparing indicator lists via default
Pydantic `__eq__` would false-positive on every shared cause_id.
Do not "fix" this by including reasoning; the exclusion is the
correct behavior. See `docs/phase5_1_general_analysis.md` locked-in
decision #2.

---

## diagnosis/output_schema.py

Pydantic models for the LLM's structured output plus a KB-aware
semantic validator. Same load-time-validation pattern as
`kb/loader.py`, applied to LLM output instead of YAML.

**Pydantic models**

```python
class CauseExplanation(BaseModel):
    cause_id: str            # must be in the ranked list; not a KB free variable
    feel_id: int             # >= 0; index into the KB cause's feels list
    technical_explanation: str  # min_length=1; LLM prose citing user's values
    bridge_to_feel: str      # min_length=1; sets up the feel that follows
    drill_ids: list[int]     # max_length=2; indices into the cause's drills

class DiagnosticOutput(BaseModel):
    summary: str                                  # min_length=1
    primary: CauseExplanation | None              # populated in diagnosis mode
    secondary: list[CauseExplanation]             # max_length=2; empty in fallback
    fallback_message: str | None                  # populated in fallback mode
```

**Model validator** — enforces the "exactly one path" rule: either
`primary` is populated (with optional `secondary`), OR
`fallback_message` is populated (with empty `secondary`). Never both,
never neither.

**DiagnosisValidationError** — subclass of `ValueError`. Raised by
`validate_against_kb`; distinct from `pydantic.ValidationError`
(which covers structural failures). Same base type so callers can
catch `ValueError` for either.

**Semantic validator**
```python
validate_against_kb(
    output: DiagnosticOutput,
    ranked_cause_ids: list[str],
    kb: KnowledgeBase,
    symptom: str | None,
) -> None
```
- No-op in fallback mode (nothing to validate against causes).
- Raises `DiagnosisValidationError` on first failure with an
  informative message suitable for feeding into an LLM retry.
- Checks: cited `cause_id` is in `ranked_cause_ids`; no duplicate
  `cause_id` across primary + secondary; `feel_id` is in range for
  each cited cause; `drill_ids` are in range for each cited cause
  (and empty when the cause has 0 drills).
- `symptom=None` signals general mode. `cause_id` → `Cause` lookup
  uses `collect_unique_causes(kb)` instead of
  `kb.get_causes(symptom)`. `cause_id` values are globally unique
  in the KB, so the resolution is unambiguous.

**Anti-hallucination boundary**: any `cause_id` the LLM emits must
have been in the ranked list surfaced to it in the prompt. This is
the mechanism that prevents the LLM from inventing causes from
training data.

**Tool schema generation**: `DiagnosticOutput.model_json_schema()`
produces the JSON schema used as the Anthropic tool's `input_schema`.
Field descriptions in the Pydantic model appear inline in the tool
schema as prompt guidance for the LLM. Single source of truth: edit
a field's description here, and the LLM's prompt updates on the
next call.

---

## diagnosis/prompt.py

Constructs the Anthropic-formatted request payload — system prompt,
user message, tool schema, tool_choice — for one diagnostic LLM
call.

**Constants**
- `NORMAL_TOP_N = 3` — max causes surfaced in diagnosis mode
- `FALLBACK_TOP_N = 5` — max causes surfaced in fallback mode
- `Mode = Literal["diagnosis", "fallback"]`

**PromptPayload dataclass**
```python
@dataclass(frozen=True)
class PromptPayload:
    system: list[dict[str, Any]]     # content blocks; stable prefix cache-marked
    messages: list[dict[str, Any]]   # single dynamic user turn
    tools: list[dict[str, Any]]      # emit_diagnosis tool; cache-marked
    tool_choice: dict[str, Any]      # forced to emit_diagnosis
```

Fields map 1:1 to `anthropic.messages.create()` parameters — unpack
into the API call.

**Public function**
```python
build_prompt(
    symptom: str | None,
    ranked: list[RankedCause],
    kb: KnowledgeBase,
    *,
    n_swings: int,
    mode: Mode,
    user_context: str = "",
) -> PromptPayload
```

**Symptom vs. mode**: two orthogonal axes. `symptom` selects between
symptom-mode (causal voice) and general-mode (observational voice)
opening paragraphs. `mode` selects between diagnosis (top causes
clear the floor) and fallback (nothing did). All four combinations
are valid — a general-mode fallback fires when no cause from the
pooled ranking clears 0.5, symptom-mode fallback fires when no
cause for that specific symptom clears 0.5.

**Cause selection by mode**
- `mode="diagnosis"`: only causes with score >=
  `FALLBACK_SCORE_FLOOR` (0.5), top `NORMAL_TOP_N`. Sub-floor causes
  are not diagnostic candidates.
- `mode="fallback"`: top `FALLBACK_TOP_N` regardless of score. The
  LLM needs to reference what came close but didn't clear the
  threshold.

**Invariant**: `mode="diagnosis"` with no cause clearing the floor
raises `ValueError`. Caller should have detected via
`should_fall_back(ranked)` and used `mode="fallback"`. Fails loud
rather than send the LLM a contradictory prompt.

**Indicator rendering** — critical detail. `_format_indicator_line`
reconstructs the mean raw feature value from a z-score using
`raw = z * baseline.stddev + baseline.mean`, so the LLM can cite
the raw measurement (in coaching units where applicable) rather
than a z-score. Both are shown; the system prompt routes citation
behavior:
- Real coaching units (degrees, seconds): LLM cites the number
  directly
- Proxy features (`*_proxy`, `*_target_axis`, `*_displacement`,
  `*_vertical_change`): LLM describes qualitatively; never quotes
  the raw number or the z-score

**Prompt caching**
- System block: `cache_control: {"type": "ephemeral"}`
- Tool schema: `cache_control: {"type": "ephemeral"}`
- User message: NOT cached (dynamic per call)

Empirical: cache_read matches cache_create across calls within the
5-minute TTL window. Effective per-call cost with cache hit
~$0.011; uncached first call ~$0.022.

**System prompt structure** (5300+ chars, stable):
1. Role and pipeline context
2. Output rules (tool-use only, no cause invention, no feel
   paraphrasing)
3. Voice — cite coaching units, describe proxies qualitatively
4. Feel selection rules (use `best_for` and `why_it_works` notes;
   consider user context)
5. Drill selection rules (0-2 per cause; empty is fine)
6. Symptom-specific framing:
   - `inconsistent_contact` — "here are where your swing varies
     most, ranked by magnitude" (variance frame, not fault frame);
     process-oriented feels
   - `shank` — brief acknowledgment of the tension/confidence
     component alongside the mechanical cause
   - all other symptoms — standard cause-ranked diagnostic frame
   - general mode (`symptom is None`) — observational opening; no
     symptom-specific branches trigger even when a matched
     cause_id lives in inconsistent_contact.yaml or shank.yaml
7. Fallback-mode rules — branches on symptom presence:
   - Symptom-mode fallback: cite closest cause; mention grip /
     alignment / weight distribution as invisible-axis blind
     spots; suggest face-on filming, more swings, clearer example.
   - General-mode fallback: cite closest observations; frame as
     "nothing stood out" rather than "we can't diagnose"; note
     the two branches (close-to-neutral vs. invisible-axis blind
     spot); suggest reporting a specific symptom if the user has
     one. Structurally harder to trigger than symptom-mode
     fallback — variance causes (stddev_gt) bypass the consistency
     filter and often catch disparate uploads that symptom mode
     would fall back on. See
     `docs/phase5_1_general_analysis.md` empirical findings.

---

## diagnosis/llm_client.py

Anthropic messages API wrapper. Handles mode auto-detection,
forced tool use, response parsing, and one retry on validation
failure.

**Constants**
- `DEFAULT_MODEL = "claude-sonnet-4-6"` — matches project spec.
  Swap to newer via constant or `model=` argument. Sonnet 5 uses
  adaptive thinking by default which adds token cost/latency for
  structured tool-use; 4.6 is a cleaner fit here.
- `DEFAULT_MAX_TOKENS = 2048` — output budget. Realistic output is
  500-1000 tokens; 2048 leaves headroom without paying for runaway.
- `DEFAULT_MAX_RETRIES = 1` — total attempts = `max_retries + 1`.
  One shot to self-correct, then raise loud. Looping is worse than
  surfacing the bug.

**Public function**
```python
generate_diagnosis(
    symptom: str | None,
    ranked: list[RankedCause],
    kb: KnowledgeBase,
    *,
    n_swings: int,
    user_context: str = "",
    client: Anthropic | None = None,       # defaults to Anthropic()
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    verbose: bool = False,                 # stderr logging per attempt
) -> DiagnosticOutput
```

**Symptom parameter**: `str | None`. Non-None values (`"slice"`,
`"hook"`, etc., must be in `SUPPORTED_SYMPTOMS`) route through the
symptom-mode prompt with causal voice. `None` routes through the
general-mode prompt with observational voice. Empty string is NOT
accepted — the API layer converts `""` to `None` before calling.

**Behavior**
1. `mode = "fallback" if should_fall_back(ranked) else "diagnosis"`
2. `payload = build_prompt(...)` with that mode; `symptom=None`
   triggers the general-mode opening paragraph and skips symptom-
   specific branches (inconsistent_contact reframe, shank caveat)
3. Loop up to `max_retries + 1` times:
   a. Call `client.messages.create(**payload)` with cache_control
      already set by build_prompt
   b. Extract the tool_use block from `response.content`
   c. Parse tool input as `DiagnosticOutput` (Pydantic)
   d. `validate_against_kb(...)` for semantic check
   e. On success: return
   f. On `ValidationError` or `DiagnosisValidationError`: append the
      malformed assistant turn plus a `tool_result` with
      `is_error=True` and the error message to messages, retry
4. If retries exhaust: raise `DiagnosisValidationError` naming the
   last error

**Retry conversation format** (semantically correct Anthropic
protocol, not plain-text scolding):
```python
messages = [
    {"role": "user", "content": original_user_msg},
    {"role": "assistant", "content": [malformed_tool_use_block]},
    {"role": "user", "content": [{
        "type": "tool_result",
        "tool_use_id": tool_use.id,
        "content": "Your emit_diagnosis call failed validation: ...",
        "is_error": True,
    }]},
]
```

**Anti-hallucination scope**: `ranked_ids` passed to
`validate_against_kb` is the FULL ranked list, not the
mode-filtered subset. This lets the LLM legitimately cite a
lower-scored cause as secondary if it wants to; only truly invented
`cause_id`s are rejected.

**Verbose logging** (to stderr, prefixed `[generate_diagnosis]`):
mode + n_ranked at entry; per-attempt API call → stop_reason +
token usage (input, output, cache_read, cache_create); validation
pass/fail per attempt.

**Failure modes**
- `DiagnosisValidationError` — output failed both attempts. Message
  names the last error.
- `RuntimeError` — API response contained no tool_use block despite
  forced tool_choice. Defensive; should not occur.
- `anthropic.*` errors (auth, rate limit, network) — propagate.

---

## pipeline.py

End-to-end orchestration: videos in, `AnalysisResult` out. This is
the module Phase 5's FastAPI route wraps.

**AnalysisResult dataclass**
```python
@dataclass(frozen=True)
class AnalysisResult:
    diagnosis: DiagnosticOutput
    annotated_video_paths: list[Path]     # empty when annotated_output_dir=None
    ranked_causes: list[RankedCause]      # for debug / observability
```

**Public function**
```python
analyze_swings(
    video_paths: list[Path],
    symptom: str | None,
    kb: KnowledgeBase,
    *,
    user_context: str = "",
    handedness: Handedness = Handedness.RIGHT_HANDED,
    cache_dir: Path = Path("data/processed"),
    annotated_output_dir: Path | None = None,
    force_extract: bool = False,
    client: Anthropic | None = None,
    verbose: bool = False,
) -> AnalysisResult
```

**Composition (no new logic; pure orchestration)**
1. Input validation — non-empty paths; if `symptom` is not None,
   must be in `SUPPORTED_SYMPTOMS` and loaded in the KB; all video
   files exist. `symptom=None` routes through general mode
   (`match_general` + general-mode prompt).
2. Eager Anthropic client init (fail fast on missing API key before
   pose extraction runs)
3. Per swing:
   a. Load pose from cache (`{cache_dir}/{stem}_pose.npz`) or
      extract fresh + save
   b. `segment_swing()` — raises `ValueError` if segmentation fails
   c. `compute_swing_features()` via orchestrator
   d. Optional: `render_segmented_pose_video()` to annotated dir
4. `aggregate(per_swing_features)` — cross-swing means/stddevs
5. Ranked causes: `match_symptom(symptom, ...)` when symptom is
   provided; `match_general(...)` when symptom is None. Both
   return `list[RankedCause]` — downstream code is mode-agnostic.
6. `generate_diagnosis(symptom, ...)` — LLM output; symptom
   threads through to `build_prompt` for voice selection.

**KB is passed in, not loaded internally**. Phase 5's API loads KB
once at startup and injects into every request. Same pattern as
`client` — dependency injection for testability.

**Cache dir semantics**
- Dev / test: `data/processed/` (default) — persists NPZs across runs
- Phase 5 production: caller passes a per-session temp dir

**Annotated output semantics**
- `annotated_output_dir=None`: skip video rendering (faster;
  `AnalysisResult.annotated_video_paths` is empty)
- Set: writes `{stem}_annotated.mp4` per input video; returns paths

**Failure model** — raises on any per-swing failure. No graceful
skipping in v1. Phase 5 can add per-video tolerance ("swing 3 of 4
failed, using the other 3") once real user data shows the need.

**Verbose logging** (stderr, prefixed `[pipeline]`): per-swing
stage progress including pose stats, checkpoint frame numbers with
confidences, feature NaN count, matcher top score. `generate_diagnosis`
adds its own `[generate_diagnosis]` lines beneath.

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

### `scripts/test_output_schema.py`
Structural + semantic validation tests for
`diagnosis/output_schema.py`. Covers Pydantic field constraints
(negative feel_id, empty strings, over-long lists), the
exactly-one-path model validator (primary+fallback both/neither,
non-empty secondary in fallback), and `validate_against_kb`
failures (hallucinated cause_id, cause_id not in ranked list,
duplicate causes, out-of-range feel_id / drill_ids).
python scripts/test_output_schema.py

### `scripts/test_prompt.py`
Sanity script for `diagnosis/prompt.py`. Builds prompts from
manually-constructed RankedCause fixtures and prints them for
eyeball inspection. Does NOT hit the Anthropic API. Three cases:
- Case A: diagnosis mode with mixed scores — verifies sub-floor
  causes filtered out
- Case B: fallback mode with all sub-floor scores — verifies
  causes surfaced for LLM to reference
- Case C: sub-floor list in diagnosis mode — verifies the invariant
  fires (`ValueError`)

Also asserts tool schema shape: name is `emit_diagnosis`,
top-level fields are `[summary, primary, secondary, fallback_message]`,
`cache_control` set on both system block and tool.
python scripts/test_prompt.py

### `scripts/test_diagnosis.py`
Spike test that ACTUALLY hits the Anthropic API. Requires
`ANTHROPIC_API_KEY` in env. Two cases using fixture-based
RankedCause (no pose pipeline):
- Case A: diagnosis mode with cupped_lead_wrist_at_top at score
  1.40 — expects primary CauseExplanation citing the cupped cause
- Case B: fallback mode with all sub-floor scores — expects
  fallback_message referencing invisible-axis blind spots (grip /
  alignment / weight / face-on)

Prints full DiagnosticOutput with feel_id resolved back to KB feel
text. Estimated cost: ~$0.03 per run.
python scripts/test_diagnosis.py

### `scripts/test_pipeline.py`
End-to-end pipeline test on REAL video data. Uses cached pose NPZs
(or re-extracts if missing). Two cases:
- Case A: swing_16 alone → diagnosis mode expected (cupped
  demo, score 1.40 on cupped_lead_wrist_at_top)
- Case B: swing_16 + swing_09 → fallback expected (60% consistency
  filter suppresses indicators that don't fire on both swings —
  design demonstration, not bug)

Estimated cost: ~$0.03 per run.
python scripts/test_pipeline.py

### `scripts/audit_kb_consistency.py`
Runs `collect_unique_causes(kb)` and reports on the diagnostic-
identity check. For every shared cause_id (appearing in 2+ symptom
files), prints the host files, confirms diagnostic content is
identical, and prints the pooled feels/drills counts (union across
files). Fails loud with `ValueError` if identity check fails —
this script is the canonical way to verify KB edits didn't
inadvertently diverge indicator thresholds across symptom files
for a shared cause. Recommended run after any KB edit touching a
shared cause_id (early_extension, hanging_back, over_the_top,
casting_early_release, reverse_pivot).
python scripts/audit_kb_consistency.py

### `scripts/test_general_matcher.py`
Sanity script for `match_general`. Runs the general-mode matcher
against real cached swings and prints the ranked list. Two cases:
- Case A: swing_16 alone → expect `cupped_lead_wrist_at_top`
  primary at score 1.40 (same firing pattern as symptom mode
  Case A, resolved through the pooled cause set)
- Case B: swing_16 + swing_09 → expect
  `inconsistent_top_of_backswing` primary at score 1.10
  (variance causes bypass consistency filter; where symptom mode
  falls back, general mode diagnoses inconsistency)

Does not hit Anthropic API. Serves as regression check for the
pooling logic and the stddev_gt bypass behavior in general mode.
python scripts/test_general_matcher.py

### `scripts/test_general_prompt.py`
Sanity script for `build_prompt` with `symptom=None`. Builds
prompts from fixture-based RankedCause lists and prints them for
eyeball inspection. Does NOT hit Anthropic API. Verifies:
- General-mode opening paragraph replaces symptom-mode opener
- No symptom-specific branches trigger (no inconsistent_contact
  reframe, no shank caveat) even when the matched cause_id lives
  in inconsistent_contact.yaml or shank.yaml
- General-mode fallback message differs from symptom-mode fallback
- Voice-guidance rules (cite coaching units, describe proxies)
  are identical to symptom mode

python scripts/test_general_prompt.py

### `scripts/test_general_pipeline.py`
End-to-end general-mode pipeline test on REAL video data.
Symptom=None throughout. Two cases (mirroring `test_pipeline.py`):
- Case A: swing_16 alone → diagnosis mode expected, observational
  voice, cupped_lead_wrist_at_top primary
- Case B: swing_16 + swing_09 → diagnosis mode expected (NOT
  fallback — variance causes fire; contrast with symptom-mode
  Case B). Variance-language framing in LLM summary.

Estimated cost: ~$0.02 per run (both cases combined). Serves as
regression check for the pooling + general-prompt + LLM voice
integration and confirms the "general mode intercepts disparate
uploads" property.
python scripts/test_general_pipeline.py

---

## Environment

- Python 3.12.13
- Virtual env at `.venv`
- Package installed editable: `pip install -e .`
- Key pins: `mediapipe==0.10.14`, `pydantic`, `pyyaml`, `anthropic`
- Runs on CPU (no GPU needed for MediaPipe Pose)