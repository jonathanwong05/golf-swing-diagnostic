> **Phase 2 update: this document is preserved as historical research.**
>
> This is the working document from Phase 0/1 that captured the
> original cause research for the v1 KB. Several causes described
> below have since been dropped from the v1 implementation because
> Phase 2 empirical testing confirmed their primary indicators
> cannot be measured reliably from down-the-line 2D pose (the
> "invisible axis" principle — see `docs/measurement_visibility_decisions.md`).
>
> **Causes dropped from v1** (kept in this document as v2 candidates):
> - Slice cause 3 (weak grip) — depended on `lead_hand_knuckle_visibility_at_P1`
> - Hook cause 3 (strong grip) — depended on `lead_hand_knuckle_visibility_at_P1`
> - Pull cause 2 (aim left) — depended on `shoulder_line_at_P1`, `hip_line_at_P1`
> - Push cause 3 (aim right) — depended on `shoulder_line_at_P1`, `hip_line_at_P1`
> - Lack-of-distance cause 5 (no ground use) — depended on `weight_distribution_proxy_at_{P4, P7}`
> - Pull cause 3 (ball position too far forward) — depended on ball detection (deferred to v2)
> - Push cause 4 (ball position too far back) — depended on ball detection (deferred to v2)
> - Thin cause 5 (ball position too far forward) — depended on ball detection (deferred to v2)
>
> **Causes with swapped primary indicators in v1:**
> - Slice cause 4 / Push cause 2 / Fat cause 2 / Thin cause 1 / Shank cause 1 (early extension): primary changed from `hip_vertical_change_P1_to_P7` (rotation-confounded) to `spine_angle_change_P1_to_P7` (delta-based, clean)
> - Slice cause 5 / Fat cause 4 (reverse pivot): primary changed from `weight_distribution_proxy_at_P4` (dropped) to `head_displacement_P1_to_P4` (weak fallback)
> - Push cause 5 / Fat cause 1 / Thin cause 4 partial (hanging back): primary changed from `weight_distribution_proxy_at_P7` (dropped) to `head_displacement_P1_to_P7_target_axis` (validated)
>
> **Wrist measurement primary side (v1):** trail-side is primary for
> down-the-line view; lead-side is corroborating only. Applies to all
> wrist-based causes. See `docs/measurement_visibility_decisions.md`.
>
> The body text below is preserved as originally written for research
> traceability and to inform v2 planning if face-on view or club
> tracking is added. For the authoritative v1 KB indicator list, see
> `docs/causes_catalog.md`. For feature-level detail, see
> `docs/features_inventory.md`.

---

Working document for v1 KB design. Each symptom section captures:
- Physical framing (what's actually happening)
- Candidate causes with indicator features and checkpoints
- Judgment calls and open questions
- Items deliberately excluded and why

This is the source material for the KB. KB entries will be authored from this document in Phase 3, with thresholds tuned against test Swings.

Slice
Physical framing: For a right-handed golfer, the ball curves hard to the right. The dominant cause is almost always that the clubface is open relative to the swing path at impact. Path can be neutral, in-to-out, or out-to-in — but if the face is open to that path, the ball slices. A secondary contributor is an out-to-in path (over-the-top), which exaggerates the curve and also starts the ball left before it curves right.
Since v1 has no club tracking, face and path are inferred from body and wrist proxies.
Candidate causes
1. Cupped lead wrist at the top (open face at P4)
Features: lead_wrist_angle_at_P4, lead_wrist_angle_at_P7
Why: The lead wrist's flex/extension is the best pose-visible proxy for clubface angle. Cupped at P4 that persists to P7 = open face at impact. Highest-confidence indicator available without club tracking.
2. Over-the-top move (out-to-in path)
Features: trail_elbow_position_at_P4_to_P7 (trail elbow moves away from body rather than dropping toward trail hip), shoulder_rotation_proxy_at_P7 (shoulders over-rotated/open at impact)
Why: Classic amateur slice pattern. Arms throw out away from the body on the downswing, swinging the club across the ball left-to-right.
3. Weak grip
Features: lead_hand_knuckle_visibility_at_P1 (how many knuckles visible on lead hand at address)
Why: Weak grip naturally returns the face open at impact. Better seen face-on than down-the-line, so this indicator is noisy in v1 — kept in the KB with low confidence_weight because it's such a common slice cause that omitting it feels wrong.
Open question: revisit after Phase 1 testing — if the indicator can't be reliably extracted from down-the-line pose, drop to v2.
4. Early extension
Features: hip_position_at_P7 vs hip_position_at_P1 (hips have moved toward the ball / toward camera in down-the-line view)
Why: Early extension forces arms to get stuck behind the body; the typical compensation is to flip the hands open through impact, opening the face. Also a cause of pushes and blocks — this indicator will appear in multiple symptoms' KBs.
5. Reverse pivot / poor weight shift
Features: head_position_at_P4 vs head_position_at_P1 (head moved toward target at top), weight_distribution_proxy_at_P4 (weight on lead foot at top, reverse of correct)
Why: Reverse pivot tends to produce a steep, out-to-in downswing — slice-conducive path. Secondary contributor, not primary.
Deliberately excluded from v1
Grip pressure, tension, "casting" — not pose-visible in any clean way
Direct clubface angle — requires club tracking
Stance alignment — hard to measure from down-the-line without ball/target line reference
Decisions and open questions
Weak grip: kept with low confidence weight, revisit after Phase 1 testing
Cause count: 5 (within the 4-6 target). May add a 6th later (e.g., chicken-winging / lead elbow bend through impact) if Phase 3 KB tuning shows a gap
Hook
Physical framing: For a right-handed golfer, the ball curves hard to the left. The mirror image of slice in terms of face-to-path relationship: the clubface is closed relative to the swing path at impact. But the underlying causes are not just "the opposite of slice" — hookers tend to be more skilled players who have over-corrected away from a slice, or players whose body stalls through impact and lets the hands flip the face closed. The cause distribution is different from slice even though the geometry mirrors it.
Since v1 has no club tracking, face and path are inferred from body and wrist proxies.
Candidate causes
1. Bowed lead wrist at the top / closed face at P4 (overdone)
Features: lead_wrist_angle_at_P4, lead_wrist_angle_at_P7
Why: The mirror of the slice's top indicator. Excessively bowed (flexed) lead wrist at P4 that persists to P7 = closed face at impact. Often seen in players who studied Dustin Johnson and overcorrected.
2. Excessive in-to-out path (the "stuck" hook)
Features: trail_elbow_position_at_P4_to_P7 (trail elbow drops too far behind the body, getting "stuck"), hip_rotation_proxy_at_P7 (hips over-rotated open while arms lag behind)
Why: When the body out-races the arms, the club approaches from too far inside. The hands then have to flip to square the face, and they typically flip past square — closed face on an in-to-out path = hook.
3. Strong grip
Features: lead_hand_knuckle_visibility_at_P1 (3+ knuckles visible on lead hand at address)
Why: Strong grip naturally returns the face closed at impact. Same noisy-indicator caveat as the weak-grip case for slice — better seen face-on than down-the-line, kept with low confidence_weight.
Open question: same as slice — revisit after Phase 1 testing.
4. Body stall through impact (hands take over)
Features: hip_rotation_proxy_at_P7 vs hip_rotation_proxy_at_P10 (hip rotation slows/stops between impact and finish), lead_arm_angle_at_P7 (lead arm collapsing/bending early through impact)
Why: When the lower body stops rotating through impact, the hands and arms have to do all the work of squaring the face — and they almost always over-square it. Classic "flippy" hook.
5. Trail hand overactive at impact
Features: trail_wrist_angle_at_P7 (trail wrist excessively flexed/breaking down at impact), lead_wrist_angle_at_P7 (paired indicator — flipping shows as cupped lead wrist + flexed trail wrist together)
Why: Trail hand "throwing" the club through impact flips the face closed late. Often paired with body stall (cause 4). Worth keeping separate because the fix and feels are different — fix for 4 is about hip rotation, fix for 5 is about quieting the trail hand.
Deliberately excluded from v1
Grip pressure / "release timing" — not pose-visible in any clean way
Direct clubface angle — requires club tracking
Stance alignment / closed stance — hard to measure from down-the-line
Decisions and open questions
Strong grip: same call as weak grip for slice — kept with low confidence weight, revisit after Phase 1
Causes 4 and 5 overlap in mechanism (both produce hand flip) but have different primary indicators and different fixes/feels. Keep separate unless Phase 3 KB tuning shows they're indistinguishable in practice
Cause count: 5
Pull
Physical framing: For a right-handed golfer, the ball starts left of the target and travels in a relatively straight line left — no significant curve. This is the key distinction from a hook (which also ends up left but curves there from a more neutral start) and from a slice (which starts left and curves right). A pull means the clubface is roughly square to the swing path at impact, but the path itself is out-to-in (going left). Face and path are matched, but both are aimed left.
The diagnostic challenge: a pull and an over-the-top slice share the same path problem. The difference is what the face is doing. So pull diagnostics overlap heavily with slice's "over-the-top" cause, with the wrist/face indicators showing square-to-path rather than open-to-path.
Candidate causes
1. Over-the-top with a square face (out-to-in path, face matches path)
Features: trail_elbow_position_at_P4_to_P7 (trail elbow moves away from body / out in front of chest), shoulder_rotation_proxy_at_P7 (shoulders open at impact), lead_wrist_angle_at_P7 (roughly neutral — not cupped, not bowed)
Why: Same path problem as the slice's over-the-top cause, but the face is square to that leftward path instead of open to it. The neutral-wrist indicator is what distinguishes pull from slice when path looks similar.
2. Aim left at address (alignment issue manifesting as pull)
Features: shoulder_line_at_P1 relative to foot line (shoulders aimed left of feet), hip_line_at_P1 similarly aimed left
Why: If the player is aimed left at setup, a perfectly "on-line" swing relative to their body will produce a ball going left. This is technically not a swing fault — it's an aim fault — but it shows up as a pull symptom. Worth flagging because the fix is completely different (alignment sticks, not swing changes).
Open question: down-the-line view sees shoulder/hip line poorly compared to face-on. This indicator is noisy in v1. Keep with low confidence_weight and a note that the system may suggest "check your alignment" as a non-swing fix.
3. Ball position too far forward in stance
Features: lead_foot_position_at_P1 relative to estimated ball position (ball appears too far toward lead foot), head_position_at_P1 relative to ball (head significantly behind ball at setup)
Why: Ball forward in the stance means the club is past the low point and already moving left (in-to-out direction has turned over to out-to-in) when it reaches the ball. Geometric, not a swing fault per se, but a common pull cause.
Open question: requires reliable ball detection in the frame. If ball position can't be extracted from the video in v1, this becomes a question for the user (free-text context) rather than a measured indicator. Worth keeping in the KB but with an availability_check flag.
4. Closed shoulders at the top with steep downswing
Features: shoulder_rotation_proxy_at_P4 (shoulders under-rotated / aimed right of square at top), then steep return path to ball
Why: Under-rotated shoulders at the top often lead to a "throwing" pattern from the top with the arms swinging across the body to compensate, producing out-to-in path with a face that closes to match.
Open question: weaker indicator, may be redundant with cause 1 (over-the-top). Keep for now and revisit in Phase 3.
Deliberately excluded from v1
Direct clubface and path measurement — requires club tracking
Grip strength as a pull cause — grip strength affects face-to-path relationship, which produces curve (slice/hook), not straight pulls
Mental/setup factors like "aiming at the wrong target" — not measurable
Decisions and open questions
Pull diagnostics are inherently harder than slice/hook because the key distinguishing feature is the absence of curve, which the tool can't see. The system relies on the user's symptom report being accurate. If the user reports "pull" but the wrist indicators look slice-like, the LLM layer should consider flagging "are you sure this is a pull and not a slice?" in the output.
Cause 2 (aim) and cause 3 (ball position) are setup issues, not swing issues. Worth tagging these in the KB as category: setup vs category: swing so the LLM can frame fixes appropriately ("before changing your swing, check your alignment").
Cause count: 5
Push
Physical framing: For a right-handed golfer, the ball starts right of the target and travels in a relatively straight line right — no significant curve. Mirror of pull: the clubface is roughly square to the swing path at impact, but the path itself is in-to-out (going right). Face and path are matched, both aimed right.
The diagnostic challenge mirrors pull's: push overlaps with hook on the path problem (both are in-to-out), and the wrist/face indicators are what distinguish them. A push has neutral wrist position at impact; a hook from the same path has a closed face.
Push is also closely related to "block" — a shot where the player gets stuck in the downswing and leaves the face open while swinging out to the right. From a diagnostic standpoint, blocks and pushes share most causes and can be treated together in the KB.
Candidate causes
1. Excessive in-to-out path with a square face (the "block-style" push)
Features: trail_elbow_position_at_P4_to_P7 (trail elbow drops behind the body, getting "stuck"), hip_rotation_proxy_at_P7 (hips over-rotated open while arms lag), lead_wrist_angle_at_P7 (roughly neutral — not bowed, not cupped)
Why: Same path problem as the hook's "stuck" cause, but the hands don't flip the face closed — they hold it square to the rightward path. The neutral-wrist indicator is what distinguishes push from hook when path looks similar.
2. Early extension (hips thrust toward ball)
Features: hip_position_at_P7 vs hip_position_at_P1 (hips moved toward the ball / toward camera in down-the-line view), often paired with head_position_at_P7 rising relative to P1
Why: Early extension forces arms to get stuck behind the body. The compensation that produces a slice is flipping the hands open; the compensation that produces a push is holding the face square while swinging out to the right. Same root cause, different hand action, different ball flight. This is why early extension appears in both slice and push KBs.
3. Aim right at address (alignment issue manifesting as push)
Features: shoulder_line_at_P1 relative to foot line (shoulders aimed right of feet), hip_line_at_P1 similarly aimed right
Why: Mirror of pull's alignment cause. If aimed right at setup, a swing on the body's line will send the ball right. Same down-the-line visibility caveat — kept with low confidence_weight, tagged as a category: setup issue.
4. Ball position too far back in stance
Features: lead_foot_position_at_P1 relative to estimated ball position (ball appears too far toward trail foot), head_position_at_P1 directly over or ahead of ball
Why: Ball back in the stance means the club hasn't reached the bottom of the arc yet when it contacts the ball — it's still moving in-to-out. Geometric cause, not a swing fault. Same availability_check caveat as pull's ball-position cause: requires ball detection or user input.
5. Hanging back on trail side through impact
Features: weight_distribution_proxy_at_P7 (weight still on trail foot at impact instead of having shifted forward), head_position_at_P7 (head behind ball, well behind P1 position)
Why: When the player fails to shift weight forward through impact, the swing bottoms out behind the ball and the club is still traveling upward and to the right when it meets the ball. Common with players who try to "help the ball up." Distinct from early extension because the body is moving away from the ball, not toward it.
Deliberately excluded from v1
Direct clubface and path measurement — requires club tracking
Grip strength as a push cause — grip strength affects curve, not straight pushes
"Swinging out to right field" intent — mental cue, not measurable
Decisions and open questions
Same caveat as pull: push diagnostics depend on the user's symptom report being accurate. If wrist indicators look hook-like but the user reported push, the LLM should consider asking "are you sure this is a straight push and not a hook?"
Cause 1 (stuck path with held face) and cause 5 (hanging back) often co-occur in practice. Indicators are different enough to keep them separate, but Phase 3 testing may show they collapse into one diagnosis with two fix options.
Early extension showing up in both slice (cause 4) and push (cause 2) is good — it reflects reality. The fix is the same (anti-early-extension drills); the feel may differ depending on which symptom the player reports.
Cause count: 5
Fat contact
Physical framing: The club strikes the ground before reaching the ball, sending a divot's worth of turf into the shot and robbing distance and direction. The geometric root cause is always the same: the low point of the swing arc is behind the ball instead of at or just ahead of it. Everything else is a story about why the low point ended up there.
This is a different category of symptom from slice/hook/pull/push. Those were about face and path; fat contact is about low-point control — where the bottom of the swing arc is in space relative to the ball. The features that matter are mostly about vertical positioning (head height, hip position, weight shift) rather than rotational/face-related ones.
Candidate causes
1. Hanging back / failed weight shift to lead side
Features: weight_distribution_proxy_at_P7 (weight still on trail foot at impact), head_position_at_P7 vs head_position_at_P1 (head has moved away from target / behind ball)
Why: The low point of the swing arc is roughly under the sternum. If the upper body stays behind the ball through impact, the low point stays behind the ball — divot before ball, fat shot. This is the single most common amateur cause of fat contact and shares features with push's cause 5.
2. Early extension (vertical version)
Features: hip_position_at_P7 vs hip_position_at_P1 (hips moved toward camera), spine_angle_at_P7 (spine more upright than at P1)
Why: When the body stands up through impact, the arms have to compensate by reaching down to find the ball. Timing this compensation is hard, and missing it short produces fat contact. (Missing it long produces thin — early extension can produce both.) Appears again in this KB because it's a root cause of so many symptoms.
3. Casting / early release (loss of wrist angle in downswing)
Features: lead_wrist_angle_at_P5_proxy (estimated from interpolation between P4 and P7 if intermediate checkpoint not reliable), trail_wrist_angle_at_P5_proxy (trail wrist losing flex / "throwing" the club from the top)
Why: When the wrists release their angle too early in the downswing, the club reaches full extension before reaching the ball — low point happens behind the ball. The "throw from the top" pattern.
Open question: this is the only cause in any symptom so far that wants information from between P4 and P7. Without P5 detection, you're either interpolating between P4 and P7 wrist angles (crude but cheap) or accepting that this cause has weaker indicator support in v1. Worth keeping but flagging as a v1 weakness — the cause is real and common, the measurement is noisy.
4. Reverse pivot at the top
Features: head_position_at_P4 vs head_position_at_P1 (head moved toward target at top), weight_distribution_proxy_at_P4 (weight on lead foot at top)
Why: Reverse pivot puts weight on the lead foot at the top, meaning the downswing starts with weight moving backward (away from target) — the opposite of what produces a forward low point. Result: fat. Already appeared in the slice KB as cause 5; here it shows up as a primary fat-contact cause.
5. Excessive forward shaft lean attempted, mistimed
Features: difficult to indicate cleanly from pose — possibly lead_wrist_angle_at_P7 (heavily bowed) combined with head_position_at_P7 (behind ball)
Why: Players trying to "compress" the ball by leaning the shaft forward sometimes overdo it and shift the bottom of the arc significantly forward — but if their weight shift doesn't match, they bottom out way before the ball. This is more of a "tried to fix something and made it worse" cause and may be uncommon enough to defer.
Open question: this cause is conceptually real but the indicators are weak and overlap with cause 1. Lean toward dropping this from v1 and revisiting if Phase 3 testing reveals fat shots that the other four causes don't explain.
Deliberately excluded from v1
Course conditions (fluffy lies, tight lies) — not in the swing
"Quitting on the shot" / deceleration — possibly visible in tempo metrics but a stretch; better to defer
Excessive knee dip / lowering through transition — interesting cause but requires reliable measurement of body height changes which pose models handle inconsistently
Decisions and open questions
Casting (cause 3) is the first cause that genuinely wants P5 detection. Worth noting in the spec's open items: if Phase 3 reveals casting is a major source of unexplained fat shots, that's an argument for expanding to P5 in a later v1 patch rather than waiting for v2.
Cause 5 (mistimed forward lean) is the weakest of the five. Provisionally drop from v1; revisit in Phase 3 if needed. Cause count goes to 4 for fat contact.
Multiple causes here also appear in other symptoms' KBs (reverse pivot, early extension, hanging back). Same observation as before: this is correct and expected. The feature extractor outputs one universal feature dict; the KB does symptom-specific scoring.
Cause count: 4 (after dropping cause 5)
This is at the low end of the 4-6 target but defensible — fat contact has fewer truly distinct root causes than ball-flight symptoms do, because almost everything fat-related traces back to low-point position, with different stories about how it got there.
Thin contact
Physical framing: The club strikes the ball with its leading edge rather than the face, contacting the ball at or above its equator. The geometric cause is the mirror of fat contact: the low point of the swing arc is too high relative to the ball — either the club bottoms out before the ball and starts rising again, or it never reaches the ball's level in the first place. Like fat contact, this is a low-point control problem, and the relevant features are vertical-positioning ones (height, posture, weight).
Thin and fat share root causes more than you'd expect. Several of the same swing patterns — early extension, casting, hanging back — can produce either depending on timing. The differentiator is usually the direction the low point has moved (too far back = fat; too high or too far forward = thin) and where the player is in the arc when they make contact.
Candidate causes
1. Early extension (the "thin" timing)
Features: hip_position_at_P7 vs hip_position_at_P1 (hips moved toward camera), spine_angle_at_P7 (more upright than at P1), head_position_at_P7 (raised relative to P1)
Why: When the body stands up through impact, the club is pulled up with it. If the arms don't compensate enough to reach down to the ball, the club catches the ball thin — leading edge into the equator. This is the same cause as fat's #2 with the opposite timing outcome. Most common amateur cause of thin contact.
2. Loss of posture / standing up through the swing
Features: spine_angle_at_P4 vs spine_angle_at_P1 (spine straighter at top), and same comparison at P7
Why: Distinct from early extension in that the player loses their forward tilt gradually throughout the swing rather than thrusting the hips toward the ball specifically. The result is similar (club is too high at impact) but the fix and feels differ — posture work vs anti-early-extension drills.
Open question: features overlap heavily with early extension. The discriminator is where the height is lost — hips moving forward (early extension) vs spine straightening without forward hip motion (loss of posture). Phase 3 testing will reveal whether these are distinguishable in practice or whether they should collapse into one cause.
3. Casting / early release (the "thin" version)
Features: lead_wrist_angle_at_P5_proxy (interpolated; wrist angle lost early in downswing), trail_wrist_angle_at_P5_proxy
Why: Mirror of casting as a fat cause. When the wrists release too early, the club reaches full extension behind the ball — but if the player then pulls up through impact (which often happens when they sense they're going to hit it fat), the club rises and catches the ball thin instead. Same root cause, fat or thin depending on whether the compensation is enough.
Same P5 caveat as in the fat KB: indicator is interpolated and noisy in v1.
4. Trying to "lift" or "help" the ball into the air
Features: weight_distribution_proxy_at_P7 (weight still on trail foot at impact), head_position_at_P7 (well behind ball), often lead_wrist_angle_at_P7 (cupped/scooping at impact)
Why: Amateur instinct to get the ball airborne by adding loft with the hands. The hands flip upward through impact, raising the club's low point at exactly the wrong moment, and the leading edge catches the equator. This is the "scoop" pattern — distinct from cause 1 (early extension) because the body may be in fine position; the hands are doing the damage.
Note: shares the cupped-wrist indicator with slice's cause 1, but here paired with weight-back features rather than face-related ones. The KB matcher's per-symptom scoring handles this correctly because the cause-context differs.
5. Ball position issue (too far forward in stance)
Features: lead_foot_position_at_P1 relative to estimated ball position
Why: If the ball is positioned too far forward, the club has already passed the low point and is on its way up when it reaches the ball — thin contact, often a topped shot. Setup cause, not a swing fault. Same availability_check flag as in pull's ball-position cause — requires ball detection or user input.
Category: setup.
Deliberately excluded from v1
Tight/firm lies amplifying thin shots — course condition, not the swing
"Looking up early" / head lift specifically as a separate cause — captured by cause 1 (early extension) and cause 2 (loss of posture) via head-position features; doesn't need its own entry
Equipment issues (lie angle, shaft length) — out of scope
Decisions and open questions
Causes 1 and 2 may collapse in Phase 3 testing. Keep them separate for now because the fixes and feels are different (anti-early-extension drills vs posture-maintenance feels). If indicators can't distinguish them, merge to a single "loss of posture/early extension" cause with two feel-cue branches.
Cause 4 (scooping) is the most diagnostically distinct cause here — it's the one where the body might look fine and the hands are the problem. Worth keeping clearly separate from causes 1-3 so the LLM can give appropriately targeted feels (hand action vs body action).
Ball position (cause 5) is the setup-category cause, mirroring how pull and push had setup causes. Same availability_check concern.
Cause count: 5
Lack of distance with solid contact
Physical framing: The ball is struck cleanly — no fat, no thin, reasonably straight — but doesn't travel as far as it should for the club used. This is fundamentally a clubhead speed problem (or an efficiency problem in how that speed is delivered to the ball). The player is making solid contact but not generating or transferring enough energy.
This symptom is structurally different from everything we've done so far. Slice/hook/pull/push are about face-and-path geometry. Fat/thin are about low-point position. Lack of distance is about kinematic efficiency — how the body sequences and how much speed the swing actually generates. The features that matter are tempo, sequence, range of motion, and lag-related measurements.
Worth being upfront about a limitation: clubhead speed itself isn't directly measurable without club tracking. Everything here is a proxy for "is the player creating and delivering speed efficiently?" The diagnosis is by negative inference — flagging the patterns that prevent speed rather than measuring speed directly.
Candidate causes
1. Insufficient body rotation / short backswing
Features: shoulder_rotation_proxy_at_P4 (shoulders under-rotated at top — significantly less than ~90° relative to address), hip_rotation_proxy_at_P4 (hips under-rotated, less than ~45°)
Why: Power in the golf swing comes largely from the stretch between hips and shoulders ("X-factor") and from the range of motion the body can build up in the backswing. A short, restricted backswing leaves no room to accelerate the club. Easiest distance leak to diagnose from pose.
2. Poor sequencing — arms-dominant downswing
Features: hip_rotation_proxy_at_P4 vs hip_rotation_proxy_at_P7 (hips have barely opened from top to impact), paired with shoulder_rotation_proxy_at_P7 (shoulders rotating ahead of or with hips rather than lagging behind)
Why: A well-sequenced swing fires hips first, then torso, then arms, then club — each segment decelerating to transfer speed to the next. When the upper body initiates the downswing, the kinetic chain is broken and the player swings with arm strength alone. Visible as hips and shoulders rotating together rather than the hips leading.
3. Casting / early loss of wrist hinge
Features: lead_wrist_angle_at_P5_proxy, trail_wrist_angle_at_P5_proxy — wrists losing hinge early in the downswing
Why: Wrist lag is one of the biggest speed multipliers in the swing — the late release of stored wrist angle is what makes the clubhead snap through impact. Casting "spends" that angle too early, robbing the swing of its accelerator. Same cause as fat/thin's casting entry; here it shows up because casting also reduces speed even when contact is still solid.
Same P5 caveat: indicator is interpolated between P4 and P7 and is noisy in v1.
4. Slow tempo / sluggish transition
Features: tempo_ratio (backswing time vs downswing time — should be roughly 3:1 for irons; problem swings often closer to 2:1 or 1.5:1, or the inverse), total_swing_duration_P1_to_P10 (notably long compared to typical iron swings)
Why: This is the one cause where you have direct measurement rather than proxy. A swing that's too slow overall, or one with the wrong rhythm (downswing not appreciably faster than backswing), simply doesn't generate clubhead speed. Tempo issues are common in older players or anxious players.
Open question: tempo is a useful diagnostic but the threshold needs Phase 3 calibration. The 3:1 ratio is a guideline, not a rule, and good players have ranged from 2:1 to 4:1.
5. Reverse weight shift / no ground use
Features: weight_distribution_proxy_at_P4 (weight not loaded onto trail foot at top), weight_distribution_proxy_at_P7 (weight not shifted to lead foot at impact)
Why: Ground reaction force is a major speed source — pushing off the trail foot into transition and posting up on the lead foot through impact. A player who doesn't shift weight forfeits this entirely. Shares features with slice's reverse-pivot cause and fat's hanging-back cause, but here it's framed as a power loss rather than a path or low-point issue.
6. Excessive in-swing arm bend / collapsed structure
Features: lead_elbow_angle_at_P4 (lead arm significantly bent at top — straight arm preserves swing radius), lead_arm_angle_at_P7 (lead arm collapsing through impact)
Why: Swing radius is a multiplier on speed — a longer radius at the same angular velocity means a faster clubhead. A bent lead arm at the top shortens the radius; a "chicken-winging" lead arm through impact does the same on the way down. Solid contact is still possible with a collapsed structure, but the swing loses speed.
Open question: lead arm bend is genuinely common and detectable, but distinguishing "slightly bent for flexibility reasons" from "collapsed and losing power" needs threshold tuning. Probably want the threshold fairly forgiving to avoid flagging older or less-flexible players for what is essentially physiological.
Deliberately excluded from v1
Equipment issues (shaft too stiff/flexible, clubs not fit for player) — out of scope, but worth having the LLM mention in the "general advice" fallback for this symptom
Strength/fitness as a root cause — not a swing fault, can't be diagnosed from a swing video
"Trying to swing too hard" / tension as a cause — not pose-visible
Strike location on the face (toe/heel hits) — requires club tracking and is more of a contact-quality issue anyway
Decisions and open questions
Six causes here, the upper end of the 4-6 target. Justifiable because lack-of-distance has more genuinely distinct mechanical sources than other symptoms. Could compress by merging cause 2 (sequencing) and cause 5 (weight shift) into "kinematic chain failure" with two indicator branches, but I'd lean toward keeping them separate — the fixes are different (sequencing drills vs weight-shift drills) and the feels are very different.
Cause 4 (tempo) is your strongest measurement here because it's directly computed rather than a proxy. Worth giving it appropriate weight in scoring.
This symptom may have the most "noisy" diagnoses in practice because the underlying variable (clubhead speed) isn't measured. Expect more reliance on the LLM's "no clear cause detected" fallback for this symptom than for slice/hook/fat/thin. That's correct behavior — better to admit uncertainty than to invent a speed diagnosis from weak proxies.
Equipment caveat worth surfacing in the LLM output for this symptom specifically. If indicators don't clearly point to one of the swing causes, the fallback should mention "your clubs being fit correctly is a major factor in distance — worth getting checked if you haven't" alongside the general swing-related advice.
Cause count: 6

Inconsistent contact
Physical framing: The player hits some shots well and some poorly, with no clear pattern they can predict. One swing might be flush, the next thin, the next fat, the next pulled. The symptom isn't a specific miss — it's the variance itself. The player wants reliability, not a different shot shape.
This symptom is fundamentally different from the other seven in a way that matters for how it's diagnosed. The other symptoms ask "what's wrong with your swing?" Inconsistent contact asks "what's inconsistent about your swing?" The diagnostic shift is from feature values to feature variance across swings.
This is where the multi-swing aggregation architecture finally pays its biggest dividend. For slice, you needed 3-5 swings to confirm the fault appears consistently. For inconsistency, you need 3-5 swings specifically to measure how much things change from swing to swing. A single swing literally cannot diagnose this symptom.
Architectural note before causes
The KB entries for this symptom score against a different kind of feature: variance metrics computed across the user's uploaded swings rather than the per-swing averaged feature values used elsewhere. For example, lead_wrist_angle_at_P7_stddev (how much wrist angle varies at impact across the 5 swings) rather than lead_wrist_angle_at_P7 (the mean value).
This means Layer 3 (Feature extraction and aggregation) needs to output two parallel feature dicts: per-swing values + cross-swing aggregates (mean, stddev, range). The slice/hook/etc. KBs check against the aggregates' means; the inconsistent-contact KB checks against the stddevs and ranges.
Worth surfacing this in the spec — it's a small architectural addition that doesn't change the overall design but does change what Layer 3 outputs. Flag it for when we revisit the spec after this research is done.
Candidate causes
1. Inconsistent setup (different swing every time starts at address)
Features: head_position_at_P1_stddev, hip_position_at_P1_stddev, weight_distribution_proxy_at_P1_stddev, spine_angle_at_P1_stddev
Why: If the player's address position is different from swing to swing, every swing starts from a slightly different geometry and will end at a slightly different place. This is the most "fixable" cause of inconsistency because it's about pre-swing positioning, not in-swing motion. Often surprisingly large effect.
2. Inconsistent tempo / rushed transition
Features: tempo_ratio_stddev (transition timing varies a lot between swings), total_swing_duration_stddev (overall swing length varies)
Why: Players who don't have a repeatable rhythm — sometimes smooth, sometimes quick — produce inconsistent contact because the body's sequencing depends on consistent timing. A rushed swing breaks sequence; a slow one releases early. When tempo varies, contact varies.
3. Inconsistent weight shift / variable low point
Features: weight_distribution_proxy_at_P7_stddev, head_position_at_P7_stddev (head position at impact varying across swings)
Why: When the player's weight ends up in different places at impact on different swings, the low point of the arc lands in different places relative to the ball. Result: sometimes fat, sometimes thin, sometimes flush — the classic "I have no idea what I'm going to hit" pattern. Very common amateur inconsistency cause.
4. Inconsistent wrist position at impact
Features: lead_wrist_angle_at_P7_stddev, trail_wrist_angle_at_P7_stddev
Why: When wrist position at impact varies, face angle varies, which means direction varies even when contact is solid. Players whose hands are "active" through impact — flipping, holding, hitting at it — show high wrist-angle variance. Distinct from cause 3 in that contact may be solid but directional control is the variable.
5. Inconsistent top-of-backswing position
Features: lead_wrist_angle_at_P4_stddev, shoulder_rotation_proxy_at_P4_stddev, head_position_at_P4_stddev
Why: If the player gets to a different top position each time — sometimes long, sometimes short, sometimes upright, sometimes flat — then the downswing has to compensate differently each time. The compensations vary, the contact varies. Often paired with cause 2 (tempo) because rushed transitions tend to come from short tops, smooth transitions from full tops.
Open question: there's overlap with cause 1 (inconsistent setup) in mechanism — both are about positional variance, just at different checkpoints. Keep separate because the fixes differ (setup drills vs backswing-feel work).
Deliberately excluded from v1
Mental factors (focus, pre-shot routine, nerves) — real causes of inconsistency, not measurable from video
Fatigue across a session — would need swing-order metadata
Lie/conditions variation — out of scope
Tension/grip-pressure variation — not pose-visible
Decisions and open questions
This is the only symptom whose diagnosis depends on having a meaningful sample size. With 3 swings, variance estimates are noisy. With 5 swings, they're more meaningful. Worth surfacing in the UI: for inconsistent contact specifically, the tool should strongly recommend 5 swings (not 3) and may want to communicate lower confidence if only 3 are uploaded.
All five causes are valid simultaneously. Unlike slice, where you're often trying to isolate "is it the wrist or the path?", an inconsistent player frequently has multiple variance sources at once. The output for this symptom may need to differ structurally — instead of ranking and presenting top 1-3 causes as "this is what's wrong," it may make more sense to present "here are the places your swing varies most" with each ranked by stddev magnitude. Worth a note for Phase 4 (LLM prompt design): the diagnostic frame for this symptom is "where to focus your repetition" rather than "what's broken."
Feel cues for this symptom are also categorically different. For slice, a feel cue corrects a specific motion. For inconsistency, useful "feels" are about repeatability — pre-shot routine, consistent setup checks, tempo metronome work, etc. Worth flagging in Phase 3 KB authoring: the feels in inconsistent_contact.yaml will read more like "process feels" than "motion feels."
Cause count: 5
Shank
Physical framing: The ball is struck by the hosel (the part of the club where the shaft meets the head) rather than the face. The ball squirts sharply right at near-90° to the target line — much more abrupt than a slice or push. The geometric cause is always the same: the hosel is too close to the ball at impact, meaning the clubhead itself is closer to the player than it should be. Either the clubhead has moved toward the player during the swing, or the player has moved toward the ball, or both.
Shanks are unique among the eight symptoms in two ways. First, they're often a "sudden onset" miss — a player who never shanks suddenly shanks several in a row, then it disappears. Second, they're terrifying to amateur players in a way that creates a feedback loop (tension → worse swing → more shanks). The diagnostic job is to identify the mechanical cause; the psychological loop is acknowledged but not something the tool can fix.
Unlike push, which shares many causes with hook, shanks have their own distinct cause set centered on the clubhead's lateral path toward or away from the player during the downswing. This is hard to measure without club tracking, but the body proxies are actually reasonably good.
Candidate causes
1. Early extension (the shank version)
Features: hip_position_at_P7 vs hip_position_at_P1 (hips moved toward camera / toward ball), spine_angle_at_P7 (more upright than at P1)
Why: When the hips thrust toward the ball through impact, the entire club moves toward the ball with them — including the hosel. This is the single most common shank cause for amateurs. Same root cause as appears in slice, push, fat, thin KBs; here it's framed as "body moving toward ball brings hosel to ball." Likely the highest-weight indicator in this KB.
2. Standing too close to the ball at address
Features: hand_distance_from_body_at_P1 (hands hanging unusually close to thighs), combined with estimated ball position if available
Why: Setup cause. If the player starts with the hands and club too close to the body, there's less margin for any in-swing drift before the hosel finds the ball. A swing that would produce a clean strike from a normal setup distance produces a shank from a too-close setup.
Category: setup. Same availability_check caveat as other setup causes that depend on ball position.
3. Out-to-in path with arms pushed away from body in transition
Features: trail_elbow_position_at_P4_to_P7 (trail elbow moves away from body / out in front of chest — the over-the-top move), hand_path_proxy_at_P5_proxy (hands moving outward away from body in early downswing)
Why: The classic "over-the-top shank." When the arms throw outward at the start of the downswing, the hosel is the leading edge of the club moving toward the ball. Distinguishable from a standard over-the-top slice in that the lateral movement is more pronounced — the hands genuinely travel outward, not just over.
Shares the trail-elbow indicator with slice's over-the-top cause. Differentiated by pairing with the hand-path-outward indicator.
4. Weight rolling onto toes through downswing
Features: difficult to measure directly from pose; possible proxies include ankle_position_at_P7 vs ankle_position_at_P1 (ankles pitched forward at impact), head_position_at_P7 (forward of P1 position toward camera)
Why: When weight shifts onto the toes during the downswing, the whole body tips toward the ball — bringing the hosel with it. Classic "diving into the ball" pattern. Often paired with cause 1 (early extension) but can occur independently in players who maintain hip position but lose balance forward.
Open question: ankle-based indicators are notoriously unreliable from 2D pose, especially down-the-line where the back foot is partially occluded. Keep this cause with a weaker confidence_weight and rely on head-position-toward-camera as the primary measurable indicator. May be more reliably diagnosed as "early extension's cousin" via head position than as a standalone.
5. Arms-disconnect / arms extending away from body in downswing
Features: lead_arm_to_torso_angle_at_P5_proxy (lead arm separating from body in early downswing), hand_distance_from_body_at_P7 (hands further from body at impact than at P1)
Why: When the arms straighten and extend away from the body coming down — often a result of trying to "reach" for the ball or losing connection — the club's path moves outward, bringing the hosel to the ball. This is the "arms-y" shank pattern, distinct from cause 3 (which is more torso-driven) and cause 1 (which is hip-driven). The fix is connection drills (towel under armpit, etc.) rather than anti-early-extension work.
Deliberately excluded from v1
Mental/tension causes ("the shanks" as a psychological loop) — real but unmeasurable; the LLM output should briefly acknowledge that shanks have a confidence component and the fix is partly about resetting mentally, but not as a measured cause
Lie angle / equipment causes (clubs too upright) — out of scope
Toe shanks (the rare opposite-direction shank off the toe) — uncommon, conflated with thin contact, defer to v2 if at all
Setup with ball too close to the toe of the club — fine point of setup that's hard to measure
Decisions and open questions
Heavy reliance on early extension — cause 1 will probably end up as the dominant diagnosis for most shanks the tool sees, because (a) early extension is genuinely the most common shank cause and (b) it's the most reliably measurable. That's fine but worth being aware of: if Phase 3 testing shows the tool diagnoses early extension for nearly every shank report, that's correct behavior, not a bug.
Causes 3 and 5 may overlap in practice. Both involve the arms moving outward; the distinction is whether it's a transition-driven over-the-top move (cause 3) or a connection/extension issue (cause 5). Keep separate because the fixes differ meaningfully (path work vs connection drills). Revisit in Phase 3 if indicators can't reliably distinguish them.
The "sudden onset" pattern is worth a note in the LLM prompt. When a player reports shanks, the LLM should consider acknowledging in the output that shanks often appear suddenly and disappear suddenly, and that working on the diagnosed cause should help break the cycle. This is the one symptom where it's worth the LLM offering brief psychological framing alongside the mechanical fix.
Cause count: 5