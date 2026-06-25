"""Render swing_01 with skeleton overlay AND checkpoint banners."""
from pathlib import Path
from golf_diagnostic.pose.extractor import load_pose
from golf_diagnostic.segmentation.detector import segment_swing
from golf_diagnostic.pose.visualizer import render_segmented_pose_video

video = Path("data/raw/swing_01.mov")
cache = Path("data/processed/swing_01_pose.npz")
output = Path("data/processed/swing_01_segmented.mp4")

pose = load_pose(cache)
seg = segment_swing(pose)

print(f"Segmentation: P1={seg.p1}, P4={seg.p4}, P7={seg.p7}, P10={seg.p10}")
print(f"Rendering to {output}...")
render_segmented_pose_video(video, pose, seg, output)
print("Done.")