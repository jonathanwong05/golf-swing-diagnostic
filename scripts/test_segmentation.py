"""Run segmentation on the cached pose data and print results."""
from pathlib import Path
from golf_diagnostic.pose.extractor import load_pose
from golf_diagnostic.segmentation.detector import segment_swing

cache = Path("data/processed/swing_01_pose.npz")

print(f"Loading pose data from {cache}...")
pose = load_pose(cache)
print(f"  {pose.n_frames} frames at {pose.fps:.2f} fps "
      f"({pose.duration_seconds:.2f}s)")

print("\nSegmenting swing...")
seg = segment_swing(pose)

print(f"\nResults:")
print(f"  P1  (address)   frame {seg.p1:3d}  ({seg.p1 / pose.fps:.2f}s)  "
      f"confidence {seg.p1_confidence:.2f}")
print(f"  P4  (top)       frame {seg.p4:3d}  ({seg.p4 / pose.fps:.2f}s)  "
      f"confidence {seg.p4_confidence:.2f}")
print(f"  P7  (impact)    frame {seg.p7:3d}  ({seg.p7 / pose.fps:.2f}s)  "
      f"confidence {seg.p7_confidence:.2f}")
print(f"  P10 (finish)    frame {seg.p10:3d}  ({seg.p10 / pose.fps:.2f}s)  "
      f"confidence {seg.p10_confidence:.2f}")
print(f"\nSuccess: {seg.success}")
if not seg.success:
    print(f"Failure reason: {seg.failure_reason}")