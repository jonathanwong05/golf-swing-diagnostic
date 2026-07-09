# Golf Swing Diagnostic

A web app that analyzes your golf swing from video and gives you a personalized diagnosis — not a score, but a specific coaching cue tied to what your body is actually doing.

<!-- TODO: hero image. Screenshot the result page (feel-quote in view) and save as docs/img/hero.png -->

## What it does

Upload 1–5 down-the-line iron swing videos, optionally report the ball-flight symptom you're fighting (slice, hook, thin contact, etc.), and the tool returns:

- The most likely mechanical cause of what you're seeing
- A **feel cue** — a sensory instruction you can take to the range (e.g. *"Feel like you're hiding the clubface from the sky at the top"*)
- The technical explanation underneath, grounded in your actual measurements
- Drills, when appropriate

If you don't know what your ball is doing, you can skip the symptom step and get a general analysis of the most notable patterns in your swing.

## Why this exists

Most golf swing analysis tools either give you a generic score (Swing Sensei) or require a human coach. This one aims at a specific gap:

1. **Symptom-driven, not score-driven.** Analysis is anchored to a ball-flight problem you actually care about, not "how good is your swing overall."
2. **Multi-swing aggregation.** A diagnosis requires evidence across several swings; single-swing anomalies get suppressed. Real ball-flight problems are consistent, so the diagnosis should be too.
3. **Feel-forward output.** Every fix is delivered as a sensory cue first, with the technical mechanics as supporting evidence — which is how coaching actually works. Telling a golfer "flex your lead wrist 15°" doesn't land; telling them "feel like you're hiding the clubface from the sky" does.

## Live demo

**<https://golf-swing-diagnostic.fly.dev/app>**

Deployed on Fly.io. First visit after an idle stretch may take a few seconds to warm up; analysis itself runs in 60–120 seconds on shared-CPU hardware (vs. ~15 seconds locally on Apple Silicon — the pipeline is CPU-bound in MediaPipe pose extraction).

## How it works

Four-layer architecture:

1. **Video processing.** MediaPipe pose extraction from each frame, cached to NPZ so downstream layers don't re-run the slow part.
2. **Swing segmentation.** Rule-based detection of P1 (address), P4 (top), P7 (impact), and P10 (finish) from smoothed wrist trajectories.
3. **Feature extraction and aggregation.** Six extractors compute 36 features per swing — wrist angles, rotation proxies, spine deltas, target-axis displacements, tempo. Cross-swing aggregates (mean, stddev) support both symptom-mode scoring and the inconsistency-focused variance path.
4. **Diagnostic reasoning.** A curated knowledge base (33 causes across 9 symptoms) matches user features against causal indicators with per-indicator confidence weights and a cross-swing consistency filter. The top-ranked cause plus the user's actual feature values go to Claude Sonnet, which produces the narrative explanation and selects the appropriate feel cue from the KB — never inventing content, only translating and picking.

The LLM is deliberately confined. It receives ranked causes and user data; it must cite a `cause_id` from the ranked list; it selects a feel by index into the KB's `feels` list rather than writing new text. Anti-hallucination is a load-bearing structural property, not a prompt request.

## Honest limits

**v1 sees only what's visible from down-the-line video.** This is a hard structural constraint, not a tuning issue. Signals that live along the camera axis — grip strength, alignment relative to the target line, weight distribution — are not measurable from this angle. Five causes are dropped from v1 for this reason (weak grip, strong grip, aim left, aim right, no ground use).

**Other v1 constraints:**

- Iron swings only (driver and wedge patterns differ enough to warrant separate KBs)
- 60 fps is enough for the P4 top-of-backswing measurements; P7 impact-frame measurements are motion-jitter noisy and marked low-confidence in the KB
- No club tracking. Wrist and hand positions serve as clubface proxies
- No user accounts or session history — analyses are stateless

**v2 direction** (roughly ranked by impact): face-on camera view, 120+ fps filming, real P5 mid-downswing detection, ball-position detection, longitudinal tracking, real club tracking. See [`docs/v2_priorities.md`](docs/v2_priorities.md).

## How it's deployed

Docker container running on Fly.io shared-CPU infrastructure. Single always-on VM (the in-memory job store doesn't survive load balancing — see [`docs/v2_priorities.md`](docs/v2_priorities.md) section 6 for the production-grade fix). Total monthly cost including Anthropic API usage sits in the low single dollars.

## Run it locally

Requires Python 3.12, ffmpeg (for browser-compatible video), and an Anthropic API key.

```bash
# 1. Clone and set up environment
git clone <repo-url>
cd golf-swing-diagnostic
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Install ffmpeg (macOS)
brew install ffmpeg
# On Linux: apt install ffmpeg / dnf install ffmpeg

# 3. Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Run the server
uvicorn golf_diagnostic.api.main:app --reload
```

Open <http://localhost:8000/app> in your browser.

**A first-swing tip:** to see what the tool produces without filming, use one of the test swings in `data/raw/`. `swing_16.mov` is the cupped-lead-wrist demo and produces a clean primary observation with the "hide the clubface from the sky" feel.

## Repository structure