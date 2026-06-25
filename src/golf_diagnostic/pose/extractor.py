"""
Pose extraction from golf swing videos using MediaPipe Pose.

The extractor returns a PoseData object with frame-aligned landmarks
and video metadata. Frames where pose detection failed are NaN-filled
so the time axis remains aligned to actual video frames.

Pose data can be cached to disk (NPZ) to avoid re-running the slow
MediaPipe inference during downstream development.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

# 33 MediaPipe Pose landmarks, each with (x, y, z, visibility).
N_LANDMARKS = 33
N_COORDS = 4


@dataclass
class PoseData:
    """Structured pose-extraction output for a single video."""

    landmarks: np.ndarray  # shape (n_frames, 33, 4); NaN where detection failed
    fps: float
    width: int
    height: int
    n_frames: int          # actual frames read, not metadata count
    detection_rate: float  # fraction of frames with a successful detection

    @property
    def duration_seconds(self) -> float:
        return self.n_frames / self.fps if self.fps > 0 else 0.0


def extract_pose(video_path: Path | str) -> PoseData:
    """
    Run MediaPipe Pose on every frame of a video.

    Returns a PoseData with NaN-filled rows for any frame where the
    pose model failed to find a person.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    mp_pose = mp.solutions.pose
    frames: list[np.ndarray] = []
    n_detected = 0

    with mp_pose.Pose(
        model_complexity=2,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
        enable_segmentation=False,
    ) as pose:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break

            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame_rgb.flags.writeable = False
            results = pose.process(frame_rgb)

            if results.pose_landmarks:
                n_detected += 1
                row = np.array(
                    [[lm.x, lm.y, lm.z, lm.visibility]
                     for lm in results.pose_landmarks.landmark],
                    dtype=np.float32,
                )
            else:
                row = np.full((N_LANDMARKS, N_COORDS), np.nan, dtype=np.float32)

            frames.append(row)

    cap.release()

    n_frames = len(frames)
    if n_frames == 0:
        raise RuntimeError(f"No frames read from {video_path}")

    landmarks = np.stack(frames, axis=0)
    detection_rate = n_detected / n_frames

    return PoseData(
        landmarks=landmarks,
        fps=fps,
        width=width,
        height=height,
        n_frames=n_frames,
        detection_rate=detection_rate,
    )


def save_pose(pose_data: PoseData, output_path: Path | str) -> None:
    """Cache extracted pose data to an NPZ file for fast reload."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        landmarks=pose_data.landmarks,
        fps=pose_data.fps,
        width=pose_data.width,
        height=pose_data.height,
        n_frames=pose_data.n_frames,
        detection_rate=pose_data.detection_rate,
    )


def load_pose(input_path: Path | str) -> PoseData:
    """Load previously cached pose data from an NPZ file."""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Pose cache not found: {input_path}")

    data = np.load(input_path)
    return PoseData(
        landmarks=data["landmarks"],
        fps=float(data["fps"]),
        width=int(data["width"]),
        height=int(data["height"]),
        n_frames=int(data["n_frames"]),
        detection_rate=float(data["detection_rate"]),
    )