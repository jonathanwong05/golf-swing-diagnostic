# Golf Swing Diagnostic Tool — Project Spec (v1)

## Goal

Build a web app where a golfer uploads multiple swing videos, reports a ball-flight symptom they're struggling with (e.g., slicing), and receives a personalized diagnosis explaining which characteristics of their swing are most likely causing that problem, along with a fix and a "feel" cue they can take to the range.

The project is a personal portfolio piece focused on building hands-on experience with modern ML frameworks (PyTorch, computer vision, LLM integration) while producing something genuinely useful to other golfers.

## What makes this different from existing tools

Tools like Swing Sensei output checkpoint scores from a single swing. This tool does three things differently:

1. **Symptom-driven, not score-driven.** Analysis is anchored to a specific ball-flight problem the user reports, not a generic "how good is your swing" score.
2. **Multi-swing aggregation.** A diagnosis requires consistent evidence across several swings, not a one-rep snapshot.
3. **Feel-forward output.** Each fix is delivered as a sensory cue (e.g., "feel like your knuckles point at the ground at the top") with the technical analysis as supporting evidence, mirroring how real coaching works.

> **Phase 2 update: rotation proxies use a projection-based measurement.**
>
> Since a down-the-line camera looks along the axis of rotation,
> true rotation is not directly measurable. The `shoulder_rotation_proxy_*`
> and `hip_rotation_proxy_*` features are unitless ratios computed
> from horizontal landmark separation normalized by a stable vertical
> body dimension (ankle-to-hip distance at P1). They capture rotation
> direction and magnitude relative to address, but not in degrees.
> KB thresholds are tuned empirically in Phase 3 rather than derived
> from geometry. See `docs/phase2_notes.md`.

> **Phase 2 update: several planned features dropped from v1 due to
> the "invisible axis" principle.**
>
> Down-the-line video cannot capture information that lives along or
> rotates around the camera's line of sight. Three planned features
> were dropped after empirical validation confirmed the failure:
> weight distribution proxy (3 fields), setup alignment lines
> (shoulder_line_at_P1, hip_line_at_P1), and grip strength
> (lead_hand_knuckle_visibility_at_P1). Schema went from 42 fields
> to 36. Five KB causes were dropped from v1 (weak grip, strong grip,
> aim left, aim right, no ground use); three causes swapped to weaker
> fallback indicators (reverse pivot, hanging back, early extension).
> Every symptom still has ≥3 causes.
>
> See `docs/measurement_visibility_decisions.md` for the principle
> and `docs/phase2_notes.md` for the empirical work behind each drop.

## Scope (v1)

### In scope

- Web app, accessible from desktop and mobile browser
- Iron swings only
- Down-the-line camera angle only
- 3-5 swing uploads per analysis (recommend 5)
- Nine symptoms supported: slice, hook, pull, push, fat contact, thin contact, lack of distance with solid contact, inconsistent contact, shank
- Optional free-text context field
- Pose-based analysis (no full club tracking; wrist/hand position as proxy for club position)
- Output: structured diagnosis with feel cue, technical explanation, and 1-2 drill recommendations (linked YouTube videos)
- LLM-generated explanations grounded in a structured knowledge base

### Explicitly out of scope for v1

- Driver, wedge, putter analysis
- Face-on or other camera angles
- Real club tracking
- Tour pro swing comparison
- Session history / longitudinal tracking
- Mobile native app
- Account system (analyses are stateless)
- Account-based personalization

## Architecture

Four layers:

### Layer 1: Video processing

- User uploads 3-5 down-the-line iron swing videos
- For each video: extract pose keypoints per frame using a pretrained pose model (MediaPipe Pose or MMPose)
- Output: time series of 2D keypoint locations

**Tech**: Python, OpenCV, MediaPipe (or MMPose if accuracy is insufficient)

### Layer 2: Swing segmentation

From keypoint time series, identify the frames corresponding to four checkpoints: P1 (address), P4 (top of backswing), P7 (impact), and P10 (finish). These four are detectable via clear motion features (swing start, hands at maximum height, club/hands at lowest point near ball, swing end) and carry the bulk of diagnostic signal for the supported symptoms.
P2, P3, P5, P6, P8, P9 are explicitly v2 scope. They add richness but few independent diagnostic indicators, and rule-based detection of them is significantly more brittle.
v2 consideration: train a small 1D CNN or temporal classifier on labeled checkpoint frames to expand to all ten.

**Tech**: NumPy, SciPy for signal processing

### Layer 3: Feature extraction and aggregation

At each of the four checkpoint frames (P1, P4, P7, P10), compute biomechanical features:

Joint angles (lead wrist, trail wrist, lead elbow, hip rotation proxy, shoulder rotation proxy, knee flex) — computed where meaningful at each checkpoint
Body positions (head displacement along target axis, head vertical change, hip displacements, hand distance from body)
Tempo metrics computed across the full swing (backswing vs downswing time ratio via P1→P4 and P4→P7 durations, total swing duration P1→P10)
Cross-swing aggregates (mean, standard deviation, range) computed for every per-swing feature above. The mean values are used by ball-flight and contact symptoms (slice, hook, pull, push, fat, thin, distance, shank). The standard deviation and range values are used specifically by the inconsistent-contact diagnostic, which scores against feature variance across the user's swings rather than feature values.

Measurement vs. communication. Where features can be measured on either side of the body (lead or trail), the system uses whichever side is more reliably visible from down-the-line view as the primary measurement, and communicates findings to the user in the conventional coaching frame (typically lead-side language). For example, cupped-face-at-top is measured primarily via trail-wrist extension (where visibility is high) but communicated as "cupped lead wrist at the top" in feels and fixes. This decoupling is intentional and structural, not a workaround. See `docs/measurement_visibility_decisions.md`.

The invisible axis principle. Features whose signal lives along or rotates around the camera's line of sight are structurally unmeasurable from down-the-line 2D pose. During Phase 2, three planned feature groups (weight distribution, setup alignment, grip strength) were confirmed to fail this test and dropped from v1. If v2 adds a face-on camera view, all three become measurable and can be restored.

**Tech**: NumPy, custom feature engineering

### Layer 4: Diagnostic reasoning (the LLM layer)

This is the core of what makes the tool useful. Three sub-steps:

**4a. Knowledge base lookup**
- Given the user's reported symptom, retrieve all KB entries for that symptom
- Each KB entry contains: cause description, measurable indicators (feature + threshold), confidence weights, fix instruction, multiple feel cues (each with metadata about when they apply), drill links

**4b. Feature matching**
- For each candidate cause, evaluate each indicator against the user's aggregated features
- Score each cause by sum of (matched indicators × confidence_weights)
- Apply consistency filter: only flag a feature as "matched" if it appears in 60%+ of the user's swings
- Rank causes by score

**4c. LLM-generated explanation**
- Pass top 2-3 ranked causes + user's actual feature values + matched indicators + user's optional free-text context to Claude API
- LLM's job: select the most appropriate feel cue from the candidates (based on what the user is currently doing and their context), and write a personalized, feel-forward explanation grounded in the specific matched evidence
- LLM is **not** generating diagnosis from scratch. It is translating structured findings into coaching language and selecting from pre-authored feels.
- For the inconsistent-contact symptom specifically, the diagnostic framing differs: instead of presenting "here is what is wrong with your swing," the output should present "here are the places where your swing varies most, ranked by magnitude." The LLM prompt for this symptom selects feels oriented toward repeatability (pre-shot routine, tempo work, setup checks) rather than motion correction.
- For the shank symptom specifically, the LLM output should briefly acknowledge that shanks often appear and disappear suddenly and have a tension/confidence component alongside the mechanical cause, framed as supplementary context rather than a measured diagnosis.

**Tech**: Anthropic Claude API (Sonnet 4.6), structured prompt templates

### Edge case: no clear cause detected

If the user reports a symptom but no KB entry's indicators match strongly:
- Output general advice about common causes of that symptom
- Recommend the user upload a video specifically demonstrating the problem (e.g., "if you reported slicing but I'm not seeing typical slice-related faults, try recording swings where you can confirm the ball flight was indeed a slice")
- Flag possible quality issue (camera angle, swing speed, lighting)

This fallback will fire more frequently for symptoms whose KB was affected by v1 measurement limits — pull and push in particular each lost two causes (alignment + ball position) to the invisible-axis principle and the v2 ball-detection deferral.

## Knowledge base design

The KB is the single most important content asset in the project. Quality of the KB largely determines quality of output.

### Structure

YAML or JSON files, one entry per (symptom, cause) pair. After Phase 2 drops, roughly 17 distinct causes remain, with several causes appearing across multiple symptoms — estimated 35-40 KB entries total covering the 9 supported symptoms.

### Example entry

```yaml
symptom: slice
cause_id: open_clubface_at_impact
priority: 1
category: swing   # or "setup" — distinguishes in-swing mechanical faults from pre-swing positioning issues
confidence: validated  # validated | plausible | weak — see docs/causes_catalog.md
description: "Clubface is open relative to the swing path at impact"

indicators:
  - feature: trail_wrist_angle_at_P4
    condition: "extended > 15 degrees"
    confidence_weight: 1.0
    reasoning: "Extended trail wrist at top = cupped lead wrist = open face"
  - feature: trail_wrist_angle_at_P7
    condition: "extended at impact"
    confidence_weight: 0.4  # motion-jitter noisy at 60fps
    reasoning: "Corroborating: open face carries through to impact"
  - feature: lead_wrist_angle_at_P4
    condition: "cupped > 15 degrees"
    confidence_weight: 0.4  # lead-side visibility low
    reasoning: "Corroborating: same fault from the other side"

fix:
  technical_instruction: "Bow your lead wrist at the top of the backswing"

feels:
  - feel: "Feel like the back of your lead hand points at the ground at the top"
    best_for: "players with visibly cupped wrist at P4"
    why_it_works: "Exaggeration of the bowed position because the actual movement needed is small"
  - feel: "Feel like you're hiding the clubface from the sky at the top"
    best_for: "players who can't visualize wrist position directly"
    why_it_works: "Reframes the cue from wrist mechanics to clubface orientation, easier to feel"

drills:
  - name: "Bowed wrist drill"
    youtube_url: "https://youtube.com/..."
```

Causes tagged category: setup are framed differently in LLM output ("before changing your swing, check this") and may be surfaced first when present, since fixing a setup issue often resolves the symptom without swing changes.

The confidence label (`validated` | `plausible` | `weak`) reflects how well the cause's primary indicator was validated during Phase 2 fault-demo testing. `validated` causes had a fault demo confirming the indicator moved in the expected direction with meaningful magnitude; `plausible` causes have correct geometry but weren't confirmed on a demo; `weak` causes are the best fallback available after Phase 2 drops removed the original primary indicator. The KB matcher's confidence_weight uses these labels: validated ≈ 1.0, plausible ≈ 0.7, weak ≈ 0.4. See `docs/causes_catalog.md`.

### Sources for KB content

- Athletic Motion Golf (3D biomechanics-based instruction)
- Be Better Golf, Clay Ballard, Monte Scheinblum (feel-heavy instructors)
- "The Plane Truth," Hogan's "Five Lessons" (classical references)
- Tour player interviews about their swing thoughts (feels)
- r/golf, GolfWRX (amateur-validated feels)

### KB build effort

Estimated 30-50 hours of focused research and encoding work. Not glamorous, but central to the project's credibility.

## Tech stack

**Backend**:
- Python 3.12+ (currently 3.12.13)
- FastAPI for the web API
- OpenCV + MediaPipe for video processing and pose estimation
- NumPy, SciPy for feature engineering
- PyYAML for KB storage
- Anthropic Python SDK for Claude API

**Frontend**:
- Simple React app, or even server-rendered HTML for v1 (lower complexity)
- Video upload component with client-side preview
- Display: side-by-side swing video with pose overlay + diagnostic report

**Deployment**:
- HuggingFace Spaces or Render free tier for the app
- No GPU required; pose models run on CPU acceptably for non-real-time
- Processing time per analysis: target under 60 seconds for 5 swings

**ML/AI framework usage**:
- PyTorch for any custom model components (e.g., if v1 segmentation needs a small CNN later)
- MediaPipe / TensorFlow Lite under the hood for pose (acceptable since the resume value is the full system, not the pose model itself)

## Cost estimates

**Claude API (Sonnet 4.6)**: roughly $0.03 per analysis without caching, dropping to under $0.01 with prompt caching enabled (knowledge base is the same every call).

- 100 analyses: ~$3
- 1,000 analyses: ~$30
- 10,000 analyses: ~$300

For development and testing, $5-10 in API credits is more than enough.

**Hosting**: Free tier on HuggingFace Spaces or Render covers v1 usage easily.

## Milestones

### Phase 1: Foundation (weeks 1-3) — COMPLETE

- Project structure, repo, basic scaffold ✓
- MediaPipe pose extraction working on sample golf swing videos ✓
- Swing segmentation (P1/P4/P7/P10 detection) using rule-based heuristics ✓
- Validated segmentation visually on 15 sample swings ✓

**Exit criterion met**: given a swing video, the system outputs a labeled set of checkpoint frames with pose overlay.

### Phase 2: Feature extraction (weeks 3-5) - COMPLETE

- Implement biomechanical feature computation at each checkpoint
- Aggregate features across multiple swings with consistency scoring
- Validate features against fault-demo dataset (~15 demos + 15 normal baseline)
- Document empirically-determined design decisions and dropped features

**Extractors completed:** wrists, rotation, posture, position (4 of 6 originally planned), tempo, interpolated_p5, orchestrator, validation script.
**Extractors dropped:** weight, setup_alignment (structural failure — see `docs/measurement_visibility_decisions.md`).

**Exit criterion**: given 3-5 swings, output an aggregated SwingFeatures dict conforming to schema.

### Phase 3: Knowledge base build (weeks 5-9, overlapping with later phases)

- Research and encode KB entries for all 9 symptoms
- Iterate on indicator thresholds based on test swings
- Author feels for each fix
- Convert confidence labels (validated/plausible/weak) into concrete `confidence_weight` numbers

**Exit criterion**: KB has ~35-40 entries, each with measurable indicators, fix, and 2-4 feels.

### Phase 4: Diagnostic engine (weeks 7-9)

- Implement feature matching and cause ranking
- Design Claude prompt template for explanation generation
- Test end-to-end on real swings, iterate on prompt quality
- Implement the "no clear cause" fallback

**Exit criterion**: given swings + symptom + KB, produce a complete diagnostic output.

### Phase 5: Frontend + deployment (weeks 9-11)

- Build upload UI with symptom dropdown and optional text field
- Display pose-overlaid video and structured report
- Deploy to free hosting tier
- End-to-end test with real users (friends who golf)
- Visualization note: For the output report, draw a synthetic shaft line by extending from the lead wrist along the lead-arm direction. Label it as "estimated shaft position" — it is not used for feature computation, only for visual readability of the pose overlay.

**Exit criterion**: anyone with the URL can use it.

### Phase 6: Polish (weeks 11-12+)

- Improve error handling and edge cases (bad video angle, swing not detected, etc.)
- Tune KB based on real user feedback
- Add basic analytics to see what symptoms users actually report

## Success criteria

Project is successful if:

1. The tool runs end-to-end on uploaded videos and produces non-generic, swing-specific diagnoses
2. Five different golfers can use it on their own swings and at least three of them say the diagnosis matched something they'd been told before by a coach or recognized as true
3. The codebase demonstrates clean separation of CV, feature engineering, KB, and LLM reasoning layers
4. The README clearly explains the architecture and the key technical decisions (why structured KB instead of raw LLM, why multi-swing aggregation, why feel-forward output, why some features were dropped)

Success is **not** measured by:

- Outperforming Swing Sensei
- Getting many users
- Diagnostic accuracy beyond the inherent limits of pose-based analysis without club tracking

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Pose estimation accuracy insufficient on fast golf swings | Test early on real swings; if MediaPipe fails, try MMPose; if still failing, reduce v1 scope to slower iron swings only |
| Swing segmentation unreliable | Start with rule-based; if too brittle, label 100 swings and train a small temporal classifier |
| KB indicator thresholds wrong | Iterate on real test swings; consider asking a local PGA instructor to review the KB |
| LLM outputs incorrect or hallucinated advice | Strict prompt: LLM may only select from KB feels, may not invent fixes. Validate output format programmatically. |
| Camera angle inconsistency from users | Enforce in UI with visual guide showing correct down-the-line setup |
| Single swing is unrepresentative | Already addressed: require 3-5 swings, only flag faults consistent across 60%+ of swings |
| v1 down-the-line-only view blind to weight, alignment, grip | Accepted as a v1 limit; documented in KB via confidence labels and "no clear cause" fallback. Restoration path via v2 face-on view is straightforward. |

## Open items to revisit

- **Whether to add face-on view in v2.** This is now the single highest-impact v2 change — would restore weight distribution, setup alignment, grip strength, and lead-side wrist visibility, and directly benefit five dropped v1 causes.
- **Whether to add club tracking in v2** (significant scope increase, but enables clubface and path measurements directly)
- **Whether to add user accounts and longitudinal tracking in v2** (enables learning which feels work for which users)
- **P5 (early downswing) detection**: three causes across fat contact, thin contact, and lack of distance want to measure wrist angle between P4 and P7 (casting / early release). v1 interpolates between P4 and P7 wrist angles, which is crude. If Phase 3 testing shows casting is a major source of unexplained misses, expanding to reliable P5 detection is the highest-leverage v1 patch — ahead of full P2-P10 expansion.
- **P7 wrist measurement is unreliable at 60fps** due to motion-induced pose-tracking jitter. v2 may recommend 120fps+ filming for users wanting accurate impact-position diagnostics.
- **Ball detection in-frame** would restore three currently-deferred setup causes (ball position too far forward, ball position too far back). Lower priority than face-on view but simpler to add.