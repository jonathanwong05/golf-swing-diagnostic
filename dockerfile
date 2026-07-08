# Golf Swing Diagnostic — HF Spaces deployment container.
#
# HF Spaces expects the app to listen on port 7860.

FROM python:3.12-slim

# System deps:
# - ffmpeg: H.264 transcode of annotated videos
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install into system site-packages as root. In a single-app
# container the user-vs-system distinction has no value.
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Copy remaining app files.
COPY kb/ ./kb/
COPY docs/ ./docs/

# Pre-download all MediaPipe pose models while we're still root and
# can write into site-packages. MediaPipe lazily downloads them on
# first use into its own install directory, which fails at runtime
# once we drop to a non-root user. Pre-warming all three complexities
# means the runtime can pick any model without triggering the write.
RUN python -c "import mediapipe as mp; \
    [mp.solutions.pose.Pose(model_complexity=n).close() for n in (0, 1, 2)]"

# HF Spaces runs containers as UID 1000. Create the user, hand
# ownership over, drop privileges before starting the app.
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user

# Runtime config.
ENV GOLF_KB_DIR=/app/kb
ENV GOLF_SESSIONS_DIR=/tmp/golf-analysis
ENV PYTHONUNBUFFERED=1

EXPOSE 7860

CMD ["uvicorn", "golf_diagnostic.api.main:app", "--host", "0.0.0.0", "--port", "7860"]