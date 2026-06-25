"""
Render pose-overlaid videos from extracted PoseData.

Decoupled from the extractor so visualization can be iterated on
without re-running MediaPipe. Reads from the original video for
frame imagery and from PoseData for landmark positions.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from golf_diagnostic.pose.extractor import PoseData
from golf_diagnostic.segmentation.detector import SwingSegmentation

# MediaPipe Pose landmark indices (a subset; we only draw what we care about).
# Full list at https://github.com/google/mediapipe/blob/master/docs/solutions/pose.md
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_ELBOW, RIGHT_ELBOW = 13, 14
LEFT_WRIST, RIGHT_WRIST = 15, 16
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28

# Skeleton connections, split by side so we can color them.
LEAD_CONNECTIONS = (  # left side, drawn green
    (LEFT_SHOULDER, LEFT_ELBOW),
    (LEFT_ELBOW, LEFT_WRIST),
    (LEFT_SHOULDER, LEFT_HIP),
    (LEFT_HIP, LEFT_KNEE),
    (LEFT_KNEE, LEFT_ANKLE),
)
TRAIL_CONNECTIONS = (  # right side, drawn red
    (RIGHT_SHOULDER, RIGHT_ELBOW),
    (RIGHT_ELBOW, RIGHT_WRIST),
    (RIGHT_SHOULDER, RIGHT_HIP),
    (RIGHT_HIP, RIGHT_KNEE),
    (RIGHT_KNEE, RIGHT_ANKLE),
)
CENTER_CONNECTIONS = (  # torso crossbars, drawn white
    (LEFT_SHOULDER, RIGHT_SHOULDER),
    (LEFT_HIP, RIGHT_HIP),
)

# BGR colors (OpenCV uses BGR, not RGB).
LEAD_COLOR = (0, 255, 0)        # green
TRAIL_COLOR = (0, 0, 255)       # red
CENTER_COLOR = (255, 255, 255)  # white
POINT_COLOR = (255, 255, 0)     # cyan, for landmark dots
BANNER_BG_COLOR = (0, 200, 255) # yellow-ish, for checkpoint banner
BANNER_TEXT_COLOR = (0, 0, 0)   # black

VISIBILITY_THRESHOLD = 0.5
LANDMARK_RADIUS = 4
LINE_THICKNESS = 2
CHECKPOINT_BANNER_PERSISTENCE = 5  # frames before/after to keep banner visible


def _to_pixel(landmark: np.ndarray, width: int, height: int) -> tuple[int, int]:
    """Convert normalized (x, y) coordinates to pixel coordinates."""
    return int(landmark[0] * width), int(landmark[1] * height)


def _draw_connection(
    frame: np.ndarray,
    landmarks_frame: np.ndarray,
    a: int,
    b: int,
    color: tuple[int, int, int],
    width: int,
    height: int,
) -> None:
    """Draw a line between two landmarks if both are visible enough."""
    if (landmarks_frame[a, 3] < VISIBILITY_THRESHOLD
            or landmarks_frame[b, 3] < VISIBILITY_THRESHOLD):
        return
    if np.isnan(landmarks_frame[a]).any() or np.isnan(landmarks_frame[b]).any():
        return
    p1 = _to_pixel(landmarks_frame[a], width, height)
    p2 = _to_pixel(landmarks_frame[b], width, height)
    cv2.line(frame, p1, p2, color, LINE_THICKNESS)


def _draw_landmarks(
    frame: np.ndarray,
    landmarks_frame: np.ndarray,
    width: int,
    height: int,
) -> None:
    """Draw individual landmark points for the joints we track."""
    indices = (
        LEFT_SHOULDER, RIGHT_SHOULDER,
        LEFT_ELBOW, RIGHT_ELBOW,
        LEFT_WRIST, RIGHT_WRIST,
        LEFT_HIP, RIGHT_HIP,
        LEFT_KNEE, RIGHT_KNEE,
        LEFT_ANKLE, RIGHT_ANKLE,
    )
    for idx in indices:
        if landmarks_frame[idx, 3] < VISIBILITY_THRESHOLD:
            continue
        if np.isnan(landmarks_frame[idx]).any():
            continue
        p = _to_pixel(landmarks_frame[idx], width, height)
        cv2.circle(frame, p, LANDMARK_RADIUS, POINT_COLOR, -1)


def _draw_skeleton_on_frame(
    frame: np.ndarray,
    landmarks_frame: np.ndarray,
    width: int,
    height: int,
) -> None:
    """Draw the full skeleton (connections + landmarks) on a single frame."""
    if np.isnan(landmarks_frame).all():
        return
    for a, b in LEAD_CONNECTIONS:
        _draw_connection(frame, landmarks_frame, a, b, LEAD_COLOR, width, height)
    for a, b in TRAIL_CONNECTIONS:
        _draw_connection(frame, landmarks_frame, a, b, TRAIL_COLOR, width, height)
    for a, b in CENTER_CONNECTIONS:
        _draw_connection(frame, landmarks_frame, a, b, CENTER_COLOR, width, height)
    _draw_landmarks(frame, landmarks_frame, width, height)


def _draw_checkpoint_banner(
    frame: np.ndarray,
    label: str,
    confidence: float,
    width: int,
) -> None:
    """Draw a checkpoint banner at the top of the frame."""
    banner_height = 80
    cv2.rectangle(frame, (0, 0), (width, banner_height), BANNER_BG_COLOR, -1)
    cv2.putText(
        frame, label, (20, 50),
        cv2.FONT_HERSHEY_SIMPLEX, 1.5, BANNER_TEXT_COLOR, 3,
    )
    cv2.putText(
        frame, f"conf {confidence:.2f}", (width - 250, 50),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, BANNER_TEXT_COLOR, 2,
    )


def _checkpoint_label_for_frame(
    frame_idx: int,
    segmentation: SwingSegmentation,
) -> tuple[str, float] | None:
    """Return (label, confidence) if this frame is within a checkpoint's persistence window."""
    checkpoints = (
        ("P1 (address)", segmentation.p1, segmentation.p1_confidence),
        ("P4 (top)", segmentation.p4, segmentation.p4_confidence),
        ("P7 (impact)", segmentation.p7, segmentation.p7_confidence),
        ("P10 (finish)", segmentation.p10, segmentation.p10_confidence),
    )
    for label, cp_frame, conf in checkpoints:
        if abs(frame_idx - cp_frame) <= CHECKPOINT_BANNER_PERSISTENCE:
            return label, conf
    return None


def render_pose_video(
    video_path: Path | str,
    pose_data: PoseData,
    output_path: Path | str,
) -> None:
    """Render an annotated copy of the input video with skeleton overlaid."""
    video_path = Path(video_path)
    output_path = Path(output_path)

    if pose_data.landmarks.shape[0] == 0:
        raise ValueError("PoseData has no frames")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(
        str(output_path), fourcc, pose_data.fps,
        (pose_data.width, pose_data.height),
    )

    frame_idx = 0
    n_pose_frames = pose_data.landmarks.shape[0]

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx < n_pose_frames:
            _draw_skeleton_on_frame(
                frame, pose_data.landmarks[frame_idx],
                pose_data.width, pose_data.height,
            )
        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()


def render_segmented_pose_video(
    video_path: Path | str,
    pose_data: PoseData,
    segmentation: SwingSegmentation,
    output_path: Path | str,
) -> None:
    """
    Render an annotated video with skeleton overlay AND checkpoint banners.

    A banner labeling P1, P4, P7, or P10 appears at the top of the frame
    on each checkpoint frame and persists CHECKPOINT_BANNER_PERSISTENCE
    frames in each direction for visibility during scrubbing.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)

    if pose_data.landmarks.shape[0] == 0:
        raise ValueError("PoseData has no frames")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(
        str(output_path), fourcc, pose_data.fps,
        (pose_data.width, pose_data.height),
    )

    frame_idx = 0
    n_pose_frames = pose_data.landmarks.shape[0]

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_idx < n_pose_frames:
            _draw_skeleton_on_frame(
                frame, pose_data.landmarks[frame_idx],
                pose_data.width, pose_data.height,
            )

        label_info = _checkpoint_label_for_frame(frame_idx, segmentation)
        if label_info is not None:
            label, conf = label_info
            _draw_checkpoint_banner(frame, label, conf, pose_data.width)

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()