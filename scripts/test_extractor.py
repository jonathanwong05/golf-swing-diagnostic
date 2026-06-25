"""Quick smoke test for the pose extractor."""
from pathlib import Path
from golf_diagnostic.pose.extractor import extract_pose, save_pose, load_pose

video = Path("data/raw/swing_01.mov")
cache = Path("data/processed/swing_01_pose.npz")

print(f"Extracting pose from {video.name}...")
pose = extract_pose(video)
print(f"  fps: {pose.fps:.2f}")
print(f"  resolution: {pose.width}x{pose.height}")
print(f"  frames: {pose.n_frames}")
print(f"  detection rate: {pose.detection_rate:.1%}")
print(f"  landmarks shape: {pose.landmarks.shape}")
print(f"  duration: {pose.duration_seconds:.2f}s")

print(f"\nSaving cache to {cache}...")
save_pose(pose, cache)

print(f"Reloading cache...")
reloaded = load_pose(cache)
assert reloaded.landmarks.shape == pose.landmarks.shape
assert reloaded.fps == pose.fps
print("Round-trip OK.")