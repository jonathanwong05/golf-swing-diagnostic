"""
Run the full Phase 1 pipeline (pose extraction → segmentation → annotated
video) over every swing video in data/raw/.

Pose data is cached to data/processed/<name>_pose.npz and reused on
subsequent runs. Pass --force to re-extract from video.

Outputs:
  data/processed/<name>_pose.npz          (cached pose data)
  data/processed/<name>_segmented.mp4     (annotated video with banners)
  data/processed/segmentation_summary.txt (per-swing results table)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from golf_diagnostic.pose.extractor import (
    extract_pose, load_pose, save_pose, PoseData,
)
from golf_diagnostic.pose.visualizer import render_segmented_pose_video
from golf_diagnostic.segmentation.detector import (
    segment_swing, SwingSegmentation,
)

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
SUMMARY_PATH = PROCESSED_DIR / "segmentation_summary.txt"
VIDEO_EXTS = (".mov", ".mp4", ".MOV", ".MP4")


def find_videos(raw_dir: Path) -> list[Path]:
    """Return all swing videos in raw_dir, sorted by name."""
    videos = []
    for ext in VIDEO_EXTS:
        videos.extend(raw_dir.glob(f"*{ext}"))
    return sorted(videos)


def get_or_extract_pose(
    video_path: Path, cache_path: Path, force: bool
) -> PoseData:
    """Load cached pose data if available, otherwise extract fresh."""
    if cache_path.exists() and not force:
        return load_pose(cache_path)
    pose = extract_pose(video_path)
    save_pose(pose, cache_path)
    return pose


def format_summary_row(
    name: str, pose: PoseData | None, seg: SwingSegmentation | None, error: str
) -> str:
    """Format one row of the summary table."""
    if error:
        return f"{name:<35} ERROR: {error}"
    assert pose is not None and seg is not None
    status = "OK" if seg.success else "FAIL"
    return (
        f"{name:<35} "
        f"frames={pose.n_frames:>3}  fps={pose.fps:>6.2f}  "
        f"detect={pose.detection_rate:>5.1%}  "
        f"P1={seg.p1:>3}({seg.p1_confidence:.2f})  "
        f"P4={seg.p4:>3}({seg.p4_confidence:.2f})  "
        f"P7={seg.p7:>3}({seg.p7_confidence:.2f})  "
        f"P10={seg.p10:>3}({seg.p10_confidence:.2f})  "
        f"{status}"
    )


def process_video(video_path: Path, force: bool) -> str:
    """Process a single video; return the summary row string."""
    name = video_path.stem
    cache_path = PROCESSED_DIR / f"{name}_pose.npz"
    annotated_path = PROCESSED_DIR / f"{name}_segmented.mp4"

    try:
        pose = get_or_extract_pose(video_path, cache_path, force)
        seg = segment_swing(pose)
        render_segmented_pose_video(video_path, pose, seg, annotated_path)
        return format_summary_row(name, pose, seg, error="")
    except Exception as e:
        return format_summary_row(name, None, None, error=str(e))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", action="store_true",
        help="Re-extract pose data even if cache exists.",
    )
    args = parser.parse_args()

    videos = find_videos(RAW_DIR)
    if not videos:
        print(f"No videos found in {RAW_DIR}")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Processing {len(videos)} videos...")
    print()

    rows = []
    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {video.name}")
        row = process_video(video, force=args.force)
        rows.append(row)

    print()
    print("=" * 130)
    print("SEGMENTATION SUMMARY")
    print("=" * 130)
    for row in rows:
        print(row)

    SUMMARY_PATH.write_text("\n".join(rows) + "\n")
    print()
    print(f"Summary written to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()