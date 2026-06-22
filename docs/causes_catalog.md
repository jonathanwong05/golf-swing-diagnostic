Body-driven causes
Early extension
Definition: Hips thrust toward the ball during the downswing; spine straightens; body height rises from address to impact.
Primary indicators: hip_position_at_P7 vs hip_position_at_P1 (moved toward camera), spine_angle_at_P7 (more upright than P1), head_position_at_P7 (raised relative to P1)
Appears in:
Slice (cause 4) — produces face-open compensation
Push (cause 2) — produces stuck-and-held compensation
Fat contact (cause 2) — body rises, arms over-compensate down → too far down
Thin contact (cause 1) — body rises, arms don't compensate enough → too high
Shank (cause 1) — body brings hosel to ball
Consistency check: This is the most-shared cause in the KB. The indicator thresholds for "how much hip movement counts as early extension" should be identical across all five files. Likely the highest-leverage cause to get measurement right.

Reverse pivot / failed weight shift to trail side
Definition: Weight stays on or moves to lead side during backswing; head moves toward target at the top.
Primary indicators: head_position_at_P4 vs head_position_at_P1 (moved toward target), weight_distribution_proxy_at_P4 (weight on lead foot at top)
Appears in:
Slice (cause 5) — produces steep, out-to-in downswing
Fat contact (cause 4) — downswing starts with weight moving backward
Consistency check: Indicators should be identical in both files. Framing differs (slice = path consequence, fat = low-point consequence) but the measurement is the same.

Hanging back / failed weight shift to lead side through impact
Definition: Weight stays on trail foot through impact; head behind ball at P7.
Primary indicators: weight_distribution_proxy_at_P7 (weight on trail foot at impact), head_position_at_P7 vs head_position_at_P1 (head moved away from target)
Appears in:
Push (cause 5) — produces upward-and-rightward path at impact
Fat contact (cause 1) — low point stays behind ball
Thin contact (cause 4, partial) — paired with scooping hands
Consistency check: Indicators should agree across these three files. Note that this is distinct from reverse pivot — reverse pivot is about weight at the top of the backswing; hanging back is about weight at impact. A player can have one without the other.

Loss of posture / standing up through the swing
Definition: Spine straightens gradually throughout the swing without specific hip thrust toward ball.
Primary indicators: spine_angle_at_P4 vs spine_angle_at_P1, spine_angle_at_P7 vs spine_angle_at_P1
Appears in:
Thin contact (cause 2)
Consistency check: Overlaps mechanically with early extension. Kept separate in the thin-contact KB because the discriminator is where the height is lost (hips moving forward vs spine straightening alone). Phase 3 will reveal whether this distinction holds up in practice or whether the two causes collapse.

Path-driven causes
Over-the-top (out-to-in path)
Definition: Trail elbow moves away from body / out in front of chest during transition; shoulders open early in downswing; club approaches ball from outside the target line.
Primary indicators: trail_elbow_position_at_P4_to_P7 (moves out instead of dropping toward trail hip), shoulder_rotation_proxy_at_P7 (shoulders open at impact)
Appears in:
Slice (cause 2) — paired with open face produces curving slice
Pull (cause 1) — paired with square face produces straight pull
Shank (cause 3) — paired with hands traveling outward produces hosel-first impact
Consistency check: Same body indicators across all three. The differentiator across these three symptoms is what the face is doing (open vs square) or what the hands are doing (traveling outward). Worth being precise in each KB entry about which secondary indicators differentiate this symptom from the others sharing the cause.

Stuck (excessive in-to-out path)
Definition: Trail elbow drops too far behind body; hips over-rotate while arms lag.
Primary indicators: trail_elbow_position_at_P4_to_P7 (drops behind body), hip_rotation_proxy_at_P7 (over-rotated open)
Appears in:
Hook (cause 2) — paired with hand flip produces curving hook
Push (cause 1) — paired with held neutral face produces straight push
Consistency check: Body indicators identical between hook and push KBs. Differentiator is lead_wrist_angle_at_P7 — closed for hook, neutral for push.

Closed shoulders at top with steep return
Definition: Shoulders under-rotated at top; downswing path is steep and over-the-top in compensation.
Primary indicators: shoulder_rotation_proxy_at_P4 (under-rotated relative to typical)
Appears in:
Pull (cause 5) — flagged as possibly redundant with over-the-top
Consistency check: Weakest cause in the catalog. Revisit in Phase 3; likely candidate for merging with pull cause 1 or dropping.

Wrist/face-driven causes
Cupped lead wrist at top (open face at P4)
Definition: Lead wrist extended/cupped beyond neutral at top of backswing; persists into impact.
Primary indicators: lead_wrist_angle_at_P4 (cupped > threshold), lead_wrist_angle_at_P7 (still cupped)
Appears in:
Slice (cause 1) — highest-confidence slice indicator
Consistency check: Single-symptom cause but the wrist angle features it uses appear in many other places (any symptom that distinguishes face position uses these features). Worth being clear that cupped values are positive and bowed values are negative (or vice versa) in the feature schema, so cross-symptom comparisons read correctly.

Bowed lead wrist at top (closed face at P4)
Definition: Lead wrist flexed/bowed beyond neutral at top.
Primary indicators: lead_wrist_angle_at_P4 (bowed past neutral), lead_wrist_angle_at_P7 (still bowed)
Appears in:
Hook (cause 1) — mirror of slice cause 1
Consistency check: Uses the same feature as slice cause 1 with opposite sign. Confirms the importance of fixing the sign convention for wrist angle in the feature schema once and using it consistently.

Scooping / flipping at impact (cupped wrist at P7)
Definition: Hands flip upward through impact, adding loft and raising low point.
Primary indicators: lead_wrist_angle_at_P7 (cupped at impact), weight_distribution_proxy_at_P7 (often paired with weight back)
Appears in:
Thin contact (cause 4)
Consistency check: Shares the cupped-wrist-at-P7 indicator with slice's cause 1, but the diagnostic context is different (slice = face open producing curve; thin = scoop producing high low-point). The KB matcher handles this correctly because scoring is per-symptom. Worth a note that this feature appearing alone (without the cupped-P4 partner) is more indicative of scoop than slice.

Body stall with hand flip through impact
Definition: Hip rotation slows or stops between impact and finish; hands take over and flip face closed.
Primary indicators: hip_rotation_proxy_at_P7 vs hip_rotation_proxy_at_P10 (rotation slows), lead_arm_angle_at_P7 (lead arm collapsing)
Appears in:
Hook (cause 4)
Consistency check: Single-symptom cause. Worth noting that cause 5 (trail hand overactive) is the "downstream" version of this — body stall is the root, trail hand flip is the consequence. Phase 3 may reveal whether to keep both or merge.

Trail hand overactive at impact
Definition: Trail wrist breaks down / over-flexes through impact, flipping face closed late.
Primary indicators: trail_wrist_angle_at_P7 (excessively flexed), paired with lead_wrist_angle_at_P7 (cupped — the flip signature)
Appears in:
Hook (cause 5)
Consistency check: Hand-action version of body stall. Kept separate because fixes differ (quiet the trail hand vs keep rotating).

Release-timing causes
Casting / early release
Definition: Wrist angle (hinge between lead arm and club) lost early in the downswing.
Primary indicators: lead_wrist_angle_at_P5_proxy, trail_wrist_angle_at_P5_proxy (both interpolated between P4 and P7 in v1)
Appears in:
Fat contact (cause 3) — club reaches full extension behind ball
Thin contact (cause 3) — paired with pull-up compensation produces thin instead of fat
Lack of distance (cause 3) — releases stored speed before impact
Consistency check: The three KB entries should use identical P5 proxy features and identical thresholds. This is the catalog's main vote for prioritizing real P5 detection in a v1 patch — three high-priority causes are all measured imprecisely. If Phase 3 testing shows the proxy gives noisy results, expanding P5 detection is more valuable than expanding to full P2-P10.

Sequencing and tempo causes
Arms-dominant downswing / broken kinetic chain
Definition: Upper body initiates downswing rather than hips; hips and shoulders rotate together rather than hips leading.
Primary indicators: hip_rotation_proxy_at_P4 vs hip_rotation_proxy_at_P7 (hips barely opened), shoulder_rotation_proxy_at_P7 (shoulders ahead of or with hips)
Appears in:
Lack of distance (cause 2)
Consistency check: Single-symptom cause. Mechanism overlaps with reverse pivot and with cause 5 below (no ground use), but the indicator pattern is distinct (rotation timing rather than weight or head position).

Slow tempo / wrong rhythm
Definition: Backswing-to-downswing time ratio off from typical (~3:1 for irons), or total swing duration unusually long.
Primary indicators: tempo_ratio, total_swing_duration_P1_to_P10
Appears in:
Lack of distance (cause 4)
Consistency check: Single-symptom cause. The only cause in the catalog measured directly rather than via proxy. Worth giving high confidence_weight when matched.

Inconsistent tempo
Definition: Tempo varies across swings — sometimes smooth, sometimes rushed.
Primary indicators: tempo_ratio_stddev, total_swing_duration_stddev
Appears in:
Inconsistent contact (cause 2)
Consistency check: The variance-version of the previous cause. Confirms the architectural decision to compute both mean and stddev for tempo metrics.

Range-of-motion causes
Insufficient body rotation / short backswing
Definition: Shoulders and/or hips under-rotated at top of backswing.
Primary indicators: shoulder_rotation_proxy_at_P4 (significantly less than ~90°), hip_rotation_proxy_at_P4 (less than ~45°)
Appears in:
Lack of distance (cause 1)
Consistency check: Single-symptom cause. The shoulder_rotation_proxy_at_P4 feature also appears in pull cause 5 ("closed shoulders at top") — same feature, different threshold direction. Worth confirming the feature is symmetric (can detect both under-rotated and over-rotated, or has a clear neutral zone).

Collapsed swing radius / bent lead arm
Definition: Lead arm bent at top (shortens radius); lead arm collapses through impact ("chicken wing").
Primary indicators: lead_elbow_angle_at_P4, lead_arm_angle_at_P7
Appears in:
Lack of distance (cause 6)
Consistency check: Single-symptom cause. Threshold needs to be forgiving — slight lead arm bend is common and not always a fault.

Connection / arm-position causes
Arms-disconnect / arms extending away from body in downswing
Definition: Lead arm separates from body during downswing; hands travel away from body line.
Primary indicators: lead_arm_to_torso_angle_at_P5_proxy, hand_distance_from_body_at_P7 (compared to P1)
Appears in:
Shank (cause 5)
Consistency check: Single-symptom cause. Distinct from over-the-top (which is torso-driven) — this is arms-only. Phase 3 may need to verify the distinction is detectable.

Weight on toes / diving into ball
Definition: Weight rolls onto toes during downswing; body tips toward ball.
Primary indicators: head_position_at_P7 (forward of P1 toward camera), ankle_position_at_P7 (proxy, noted unreliable)
Appears in:
Shank (cause 4)
Consistency check: Single-symptom cause with explicitly noted measurement weakness. Likely diagnosed in practice as a partner of early extension rather than independently. Low confidence_weight indicated.

Setup causes
These are pre-swing positioning issues, not in-swing motion. Tagged category: setup in the KB. All share the property that they should be framed differently in LLM output ("before changing your swing, check this") and may benefit from being surfaced first when present.
Aim left (alignment cause of pull)
Indicators: shoulder_line_at_P1 aimed left of feet, hip_line_at_P1 similarly
 Appears in: Pull (cause 2)
Aim right (alignment cause of push)
Indicators: shoulder_line_at_P1 aimed right of feet, hip_line_at_P1 similarly
 Appears in: Push (cause 3)
Ball position too far forward
Indicators: lead_foot_position_at_P1 relative to ball, head_position_at_P1 (behind ball)
 Appears in: Pull (cause 3), Thin contact (cause 5)
Ball position too far back
Indicators: lead_foot_position_at_P1 relative to ball, head_position_at_P1 (over or ahead of ball)
 Appears in: Push (cause 4)
Standing too close to ball
Indicators: hand_distance_from_body_at_P1
 Appears in: Shank (cause 2)
Weak grip
Indicators: lead_hand_knuckle_visibility_at_P1 (fewer knuckles visible)
 Appears in: Slice (cause 3) — kept with low confidence due to down-the-line visibility limits
Strong grip
Indicators: lead_hand_knuckle_visibility_at_P1 (more knuckles visible)
 Appears in: Hook (cause 3) — same caveat as weak grip
Consistency check across all setup causes: All ball-position causes share the availability_check concern — they depend on reliable ball detection in the frame, or on falling back to user input. The schema should support indicators that may not be measurable, with the KB matcher treating "feature unavailable" differently from "feature did not match." Worth a Phase 4 design note.

Variance causes (inconsistent-contact-specific)
These causes are unique to the inconsistent-contact symptom because they score against feature variance (stddev/range) rather than feature values.
Inconsistent setup
Indicators: head_position_at_P1_stddev, hip_position_at_P1_stddev, weight_distribution_proxy_at_P1_stddev, spine_angle_at_P1_stddev
Inconsistent weight shift / variable low point
Indicators: weight_distribution_proxy_at_P7_stddev, head_position_at_P7_stddev
Inconsistent wrist position at impact
Indicators: lead_wrist_angle_at_P7_stddev, trail_wrist_angle_at_P7_stddev
Inconsistent top-of-backswing position
Indicators: lead_wrist_angle_at_P4_stddev, shoulder_rotation_proxy_at_P4_stddev, head_position_at_P4_stddev
(Inconsistent tempo — covered above under sequencing/tempo)
Consistency check across variance causes: Every per-swing feature referenced in any non-inconsistency cause should also be available as a stddev/range variant for use here. The features inventory (Document 2) will make this explicit.

Cross-cutting observations from the catalog
Count of distinct causes: ~22. Down from 45 cause entries across nine symptoms. About half the causes are single-symptom; the other half appear in 2-5 symptoms with consistent indicators and varying interpretation.
The five "root" causes (appearing in 3+ symptoms): early extension, casting, over-the-top, hanging back, reverse pivot. These deserve the most careful threshold tuning in Phase 3 — getting them right benefits multiple symptoms simultaneously.
Two causes flagged for likely merging in Phase 3: loss of posture (thin cause 2) with early extension; closed shoulders at top (pull cause 5) with over-the-top.
Three causes that need P5 detection all involve casting. This is the catalog's strongest argument for prioritizing P5 detection as a v1 patch.
Five causes use the same feature with opposite-direction thresholds: cupped vs bowed wrist, under-rotated vs over-rotated shoulders, ball-forward vs ball-back, aim-left vs aim-right, weak vs strong grip. Confirms the feature schema needs to handle direction cleanly (signed values rather than separate features).