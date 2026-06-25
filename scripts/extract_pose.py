"""
Extract MediaPipe pose keypoints from a golf swing video and save an
annotated copy with keypoints overlaid. Used for visual QA of input
videos and the pose model.

Usage:
    python scripts/extract_pose.py path/to/input.mov path/to/output.mp4
"""

import sys
from pathlib import Path

import cv2
import mediapipe as mp


def extract_pose(input_path: Path, output_path: Path) -> None:
    mp_pose = mp.solutions.pose
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles

    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Input: {input_path.name}")
    print(f"  Resolution: {width}x{height}")
    print(f"  FPS: {fps:.2f}")
    print(f"  Frames: {total_frames}")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    frames_with_pose = 0
    frame_idx = 0

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

            # MediaPipe expects RGB.
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame_rgb.flags.writeable = False
            results = pose.process(frame_rgb)
            frame_rgb.flags.writeable = True

            annotated = frame_bgr.copy()
            if results.pose_landmarks:
                frames_with_pose += 1
                mp_drawing.draw_landmarks(
                    annotated,
                    results.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS,
                    landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style(),
                )

            writer.write(annotated)
            frame_idx += 1

            if frame_idx % 30 == 0:
                print(f"  Processed {frame_idx}/{total_frames} frames", end="\r")

    cap.release()
    writer.release()

    print()
    print(f"  Frames with pose detected: {frames_with_pose}/{frame_idx} "
          f"({100 * frames_with_pose / max(frame_idx, 1):.1f}%)")
    print(f"  Wrote: {output_path}")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python scripts/extract_pose.py <input_video> <output_video>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    extract_pose(input_path, output_path)


if __name__ == "__main__":
    main()