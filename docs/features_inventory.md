Conventions
Before listing features, three conventions to lock in now so the schema is consistent:
1. Signed values for direction. Where a feature can vary in two directions (cupped vs bowed wrist, aim left vs aim right), use a single signed feature rather than two separate features. Convention: positive = one direction, negative = the other, zero = neutral. Document the sign convention per feature.
2. _proxy suffix for inferred features. Any feature that isn't measured directly from pose keypoints but inferred from them (hip rotation from hip-keypoint angles, shoulder rotation from shoulder-keypoint angles, weight distribution from foot/hip positions) gets the _proxy suffix. Makes it visible in the KB which indicators are direct measurements vs estimates.
3. _at_P5_proxy for between-checkpoint features. Features that want a value at P5 in v1 get computed by interpolating between P4 and P7 wrist/arm angles. The suffix doubles up — _at_P5_proxy — to flag both that the checkpoint is interpolated and that the underlying feature is a proxy. If P5 detection is added in a v1 patch, these become _at_P5 and the interpolation logic is replaced.
P1 features (address)
Joint angles and positions
lead_wrist_angle_at_P1 — flex/extension of lead wrist at address. Signed: positive = cupped, negative = bowed. Used: variance only (inconsistent-contact uses _stddev form).
trail_wrist_angle_at_P1 — same for trail wrist. Used: variance only.
spine_angle_at_P1 — forward tilt of spine from vertical, measured in 2D from shoulder-to-hip line vs vertical. Used: baseline for spine-angle comparisons at P4 and P7 (loss of posture, early extension); variance form for inconsistent setup.
Body positions
head_position_at_P1 — 2D position of head/nose keypoint. Used as reference point for head-movement features at P4, P7. Variance form used for inconsistent setup.
hip_position_at_P1 — 2D position of mid-hip point (midpoint between hip keypoints). Reference for hip-movement features at P7. Variance form used for inconsistent setup.
weight_distribution_proxy_at_P1 — estimate of weight balance lead-vs-trail, computed from relative hip and foot keypoint positions. Variance form used for inconsistent setup.
Alignment (setup category, noisy from down-the-line)
shoulder_line_at_P1 — angle of line between shoulder keypoints relative to a reference (camera axis or estimated target line). Signed: positive = aimed right, negative = aimed left. Used by pull cause 2 and push cause 3. Noted as down-the-line-noisy.
hip_line_at_P1 — same for hip keypoints. Same caveats.
Hand/grip position (setup category, some noisy)
lead_hand_knuckle_visibility_at_P1 — proxy for grip strength, estimated from lead hand keypoint orientation relative to forearm. Signed or categorical (1-4 knuckles). Used by slice cause 3 (weak grip) and hook cause 3 (strong grip). Noted as down-the-line-noisy with low confidence_weight.
hand_distance_from_body_at_P1 — perpendicular distance from hands to thighs/body line at address. Used by shank cause 2 (standing too close).
Ball-position-dependent features (availability check needed)
lead_foot_position_at_P1 relative to estimated ball position. Used by pull cause 3, push cause 4, thin contact cause 5. Requires reliable ball detection in frame or fallback to user input. Schema should support "feature unavailable" distinct from "feature did not match."
P4 features (top of backswing)
Wrist angles
lead_wrist_angle_at_P4 — same definition as P1 (signed: + cupped, − bowed). Used by slice cause 1 (cupped) and hook cause 1 (bowed). The single most-referenced wrist feature in the KB. Variance form used by inconsistent contact cause 5.
trail_wrist_angle_at_P4 — same for trail wrist. Used in paired analyses but no symptom uses it as a primary indicator at P4.
Rotation proxies
shoulder_rotation_proxy_at_P4 — angle of shoulder line at top relative to address shoulder line, in the swing plane. Signed: positive = full rotation, lower magnitude = under-rotated. Used by lack-of-distance cause 1 (under-rotated) and pull cause 5 (closed/under-rotated). Variance form used by inconsistent contact cause 5.
hip_rotation_proxy_at_P4 — same for hip line. Used by lack-of-distance cause 1.
Body position
head_position_at_P4 vs head_position_at_P1 — head movement during backswing. Signed: positive = toward target (reverse pivot), negative = away from target. Used by slice cause 5, fat contact cause 4. Variance form used by inconsistent contact cause 5.
weight_distribution_proxy_at_P4 — weight at top of backswing. Used by slice cause 5, fat contact cause 4 (both reverse-pivot indicators).
spine_angle_at_P4 vs spine_angle_at_P1 — posture maintenance through backswing. Used by thin contact cause 2 (loss of posture).
Arm structure
lead_elbow_angle_at_P4 — bend in lead arm at top. Used by lack-of-distance cause 6 (collapsed radius).
P5 features (interpolated, v1 only)
All features here are interpolated between P4 and P7. Flagged for upgrade to direct P5 detection if Phase 3 testing shows casting diagnoses are noisy.
lead_wrist_angle_at_P5_proxy — wrist angle in early downswing. Used by fat contact cause 3, thin contact cause 3, lack-of-distance cause 3 (all casting-related).
trail_wrist_angle_at_P5_proxy — same for trail wrist. Used by same three causes.
lead_arm_to_torso_angle_at_P5_proxy — angle between lead arm and torso in early downswing (connection indicator). Used by shank cause 5.
hand_path_proxy_at_P5_proxy — direction of hand movement in early downswing (outward vs inward relative to body). Used by shank cause 3.
Note: hand_path_proxy_at_P5_proxy is the most ambiguously defined feature in the KB. Needs a precise definition before Phase 2 — likely the angle between (P4-to-P5 hand vector) and (vertical, or the body line). Worth resolving before building.
P7 features (impact)
This checkpoint has the highest feature density — most diagnostic signal lives here.
Wrist angles
lead_wrist_angle_at_P7 — signed (+ cupped, − bowed). Used by slice cause 1, hook cause 1, pull cause 1 (neutral), push cause 1 (neutral), thin contact cause 4 (cupped/scoop), hook cause 5 (paired with trail wrist for flip detection). Variance form used by inconsistent contact cause 4. The single most-referenced feature in the entire KB.
trail_wrist_angle_at_P7 — signed. Used by hook cause 5 (excessively flexed = flip). Variance form used by inconsistent contact cause 4.
Rotation proxies
shoulder_rotation_proxy_at_P7 — shoulder angle at impact. Used by slice cause 2 (over-rotated/open), pull cause 1, lack-of-distance cause 2 (sequencing).
hip_rotation_proxy_at_P7 — hip angle at impact. Used by hook cause 2 (over-rotated), pull cause 4 (over-rotated), push cause 1 (over-rotated while arms lag), lack-of-distance cause 2.
hip_rotation_proxy_at_P7 vs hip_rotation_proxy_at_P10 — hip rotation through finish (used as derived feature). Used by hook cause 4 (rotation slowing/stopping).
Body positions
head_position_at_P7 vs head_position_at_P1 — head movement to impact. Signed: positive = toward target, negative = away. Used by push cause 5 (hanging back), fat contact cause 1 (hanging back), thin contact cause 1 (raised relative to P1), thin contact cause 4 (paired with scoop), shank cause 1 (raised), shank cause 4 (forward toward camera). Variance form used by inconsistent contact cause 3.
hip_position_at_P7 vs hip_position_at_P1 — hip movement to impact. Signed in down-the-line view: positive = toward camera (early extension), negative = away. Used by slice cause 4, push cause 2, fat contact cause 2, thin contact cause 1, shank cause 1. Tied with lead_wrist_angle_at_P7 for most-referenced feature.
spine_angle_at_P7 vs spine_angle_at_P1 — posture at impact. Used by thin contact cause 2, shank cause 1.
weight_distribution_proxy_at_P7 — weight balance at impact. Used by push cause 5, fat contact cause 1, thin contact cause 4. Variance form used by inconsistent contact cause 3.
Arm position
trail_elbow_position_at_P4_to_P7 — derived feature tracking trail elbow path through transition. Signed: positive = out (over-the-top), negative = under (stuck). Used by slice cause 2, hook cause 2, pull cause 1, push cause 1, shank cause 3. Five-symptom feature; carefully define and tune the threshold.
lead_arm_angle_at_P7 — bend in lead arm at impact (chicken-winging). Used by hook cause 4, lack-of-distance cause 6.
hand_distance_from_body_at_P7 — hand position relative to body at impact (compared against hand_distance_from_body_at_P1). Used by shank cause 5.
Ankle position (flagged as unreliable)
ankle_position_at_P7 vs ankle_position_at_P1 — proxy for "diving onto toes." Used by shank cause 4. Noted as unreliable from down-the-line; kept with low confidence_weight.
P10 features (finish)
hip_rotation_proxy_at_P10 — used only in the derived feature hip_rotation_proxy_at_P7 vs hip_rotation_proxy_at_P10 (hook cause 4, body stall).
P10 has minimal independent diagnostic use in v1 — it functions mostly as a sanity check that the swing completed and as the reference for the rotation-slowing indicator. Worth noting that the KB could plausibly drop P10 from feature extraction entirely if hip rotation through finish is the only signal it provides; instead just compute hip rotation at the latest detected frame after P7. Keep as-is for now; revisit in Phase 2 if implementation overhead is significant.
Whole-swing features (no checkpoint)
tempo_ratio — backswing duration (P1→P4) divided by downswing duration (P4→P7). Used by lack-of-distance cause 4. Variance form (tempo_ratio_stddev) used by inconsistent contact cause 2.
total_swing_duration_P1_to_P10 — total swing time. Used by lack-of-distance cause 4. Variance form used by inconsistent contact cause 2.
These are the only directly-measured features in the KB — everything else is a proxy or position-based. Worth giving them appropriate confidence weight when matched.
Variance features (computed across user's 3-5 swings)
Every feature listed above must have a _stddev form computed across the user's uploaded swings. Used by inconsistent contact KB entries. The KB schema may also benefit from _range (max minus min) for some features where range is more interpretable than stddev — defer that decision to Phase 3 when authoring those KB entries.
Feature count summary
P1 features: 11 (including ball-position-dependent ones)
P4 features: 7
P5 features (interpolated): 4
P7 features: 12
P10 features: 1 (used only in derived form)
Whole-swing features: 2
Total distinct features: ~36
Plus variance versions of every feature for inconsistent-contact scoring
That's the v1 feature extractor's build target.
High-leverage features
A few features power most of the diagnostic work. If Phase 2 testing shows reliability problems with any of these, the diagnosis quality drops materially:
lead_wrist_angle_at_P7 — 6 causes across 5 symptoms
hip_position_at_P7 vs hip_position_at_P1 (early extension) — 5 causes across 5 symptoms
trail_elbow_position_at_P4_to_P7 — 5 causes across 5 symptoms
head_position_at_P7 vs head_position_at_P1 — 6 causes across 6 symptoms
lead_wrist_angle_at_P4 — 2 causes (slice and hook) but they're the highest-priority indicators in those symptoms
These five features are where to focus initial pose-model validation in Phase 1. If MediaPipe handles these accurately on real swings, the rest of the system has a foundation. If it doesn't, the KB's value is limited regardless of how well the other features work.
Features flagged as underspecified
Three features need precise definitions before Phase 2 implementation:
hand_path_proxy_at_P5_proxy (shank cause 3) — exact computation undefined
weight_distribution_proxy_at_P1/P4/P7/P10 — defined conceptually as "estimate from hip/foot keypoints" but the exact formula matters. Worth choosing one method (e.g., hip midpoint horizontal position relative to ankle midpoint, normalized by stance width) and using it consistently across all checkpoints.
Resolve these in the transition from research to Phase 2, before any feature-extraction code is written.
Features flagged as noisy or unreliable
Four features have known measurement weaknesses in down-the-line view and are kept in the KB with low confidence_weight:
shoulder_line_at_P1 / hip_line_at_P1 (alignment) — better measured face-on
lead_hand_knuckle_visibility_at_P1 (grip strength) — better measured face-on
ankle_position_at_P7 (diving onto toes) — back foot partially occluded
Ball-position-dependent features — depend on reliable ball detection
These should be tracked in the KB schema as low-confidence indicators and may be auto-suppressed in v1 output until Phase 3 testing validates them.