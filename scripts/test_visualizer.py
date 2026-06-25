"""Smoke test for the visualizer."""
from pathlib import Path
from golf_diagnostic.pose.extractor import load_pose
from golf_diagnostic.pose.visualizer import render_pose_video

video = Path("data/raw/swing_01.mov")
cache = Path("data/processed/swing_01_pose.npz")
output = Path("data/processed/swing_01_annotated.mp4")

print(f"Loading cached pose data from {cache}...")
pose = load_pose(cache)
print(f"  {pose.n_frames} frames at {pose.fps:.2f} fps")

print(f"Rendering annotated video to {output}...")
render_pose_video(video, pose, output)
print("Done.")