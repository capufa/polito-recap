# PoliTo Recap: the app plus everything a lecture needs — ffmpeg, Whisper, RapidOCR. The
# vendors' programs that write the report with a subscription (Claude Code, Codex, Antigravity
# CLI) are not in it: the setup installs the one chosen (recap/report/program.py). GitHub
# builds the published image on every release (.github/workflows/release.yml).
FROM python:3.12-slim-bookworm

# ffmpeg for audio and frames; libgl1 and libglib2.0-0 for OpenCV, which comes with
# RapidOCR; tzdata for local time (trash dates, logs); curl for the vendors' install scripts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 tzdata curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY recap /app/recap
# The template the setup starts .env from (recap/setup.py).
COPY .env.example /app/

# The version, for the "new version available" notice (recap/updates.py): the release
# workflow passes the tag's number (1.2.3); a local build is "dev". The image labels
# (source, license) come from the release workflow.
ARG VERSION=dev
RUN echo "${VERSION}" > /app/VERSION

RUN useradd --uid 1000 --create-home app
USER app
WORKDIR /app
# HF_HOME: the models folder: Whisper's weights (downloaded on the first lecture) and the OCR
# sizes other than small (downloaded on first use).
ENV HF_HOME=/models PYTHONUNBUFFERED=1 TZ=Europe/Rome
EXPOSE 8470
CMD ["python", "-m", "recap", "--courses", "/courses", "--listen", "0.0.0.0:8470"]
