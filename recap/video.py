"""The lecture's file: its duration and the audio (from an mp3 too); from the video, the frames,
the slide box and the visual segments.

One frame per second is enough: a slide stays on screen for tens of seconds and the
transcript is accurate to the second. Frames are scaled down to 480 px because they only
serve to decide "has something changed?" and "which page is it?"; for a screen without a
slide (OCR reads it, the page shows it) the full frame is taken again from the video.
"""
from __future__ import annotations

import json
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image

from .storage import Lecture, atomic
from .timecode import hhmmss, seconds

SAMPLE_RATE = 16000        # Hz: the rate of audio.wav, the one Whisper wants
FRAME_WIDTH = 480
CHANGE_THRESHOLD = 0.06  # fraction of the hash bits that must change
MIN_DURATION = 3         # seconds: below this, the segment is a transition and merges with the previous one


@dataclass
class Segment:
    """A span of video in which the screen does not change. Whole seconds, both ends included."""
    start: int
    end: int

    @property
    def center(self) -> int:
        return (self.start + self.end) // 2

    @property
    def span(self) -> dict:
        """As written in the JSON files: {"from", "to"} in HH:MM:SS, with "to" the second after the end."""
        return {"from": hhmmss(self.start), "to": hhmmss(self.end + 1)}

    @classmethod
    def from_span(cls, span: dict) -> Segment:
        return cls(seconds(span["from"]), seconds(span["to"]) - 1)


def duration(media: Path) -> float:
    """The seconds of the lecture's file, video or audio."""
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(media)],
                            capture_output=True, text=True, check=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def extract_audio(media: Path, wav: Path, duration: float, on_progress: Callable[[float], None]) -> None:
    """Mono PCM at SAMPLE_RATE, from the video or the mp3: the format Whisper wants."""
    with atomic(wav) as partial:
        _ffmpeg("-i", str(media), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(partial),
                duration=duration, on_progress=on_progress)


def extract_frames(mp4: Path, folder: Path, duration: float, on_progress: Callable[[float], None]) -> None:
    """One frame per second, scaled down to FRAME_WIDTH, in a folder that arrives whole."""
    with atomic(folder) as partial:
        partial.mkdir(parents=True)
        _ffmpeg("-i", str(mp4), "-vf", f"fps=1,scale={FRAME_WIDTH}:-1", str(partial / "%05d.png"),
                duration=duration, on_progress=on_progress)


def frame_path(folder: Path, second: int) -> Path:
    return folder / f"{second + 1:05d}.png"


def screen(lecture: Lecture, second: int) -> Path:
    """The full-resolution frame of a given second, for OCR and for the page: extracted from
    the video the first time it is needed, then read from work/screens/. This way the screens
    rebuild themselves, even in a lecture restored from the NAS, where they are missing."""
    png = lecture.screen(second)
    if not png.exists():
        lecture.screens.mkdir(exist_ok=True)
        with atomic(png) as partial:
            _ffmpeg("-ss", str(second), "-i", str(lecture.media), "-frames:v", "1", str(partial))
    return png


def slide_box(folder: Path) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of the slide inside the frame: the largest bright area, median
    over 40 scattered frames. A white slide on a black background, with the lecturer's
    webcam in a corner, has a sharp and stable box. If no frame has a bright area,
    ValueError: there is no slide to recognize."""
    frames = sorted(folder.glob("*.png"))
    sample = frames[:: max(1, len(frames) // 40)]
    boxes = [b for b in (_bright_box(Image.open(p)) for p in sample) if b]
    if not boxes:
        raise ValueError("no slide can be recognized in the video: no frame has a bright area "
                         "(dark-themed slides, or a screen without slides)")
    return tuple(int(np.median([b[i] for b in boxes])) for i in range(4))


def visual_segments(folder: Path, box: tuple[int, int, int, int]) -> list[Segment]:
    """The sequence of spans in which the slide does not change."""
    segments: list[Segment] = []
    previous = None
    for second, p in enumerate(sorted(folder.glob("*.png"))):
        h = _dhash(Image.open(p).crop(box))
        if previous is None or (h != previous).mean() > CHANGE_THRESHOLD:
            segments.append(Segment(second, second))
        else:
            segments[-1].end = second
        previous = h
    return _merge_short(segments)


def _merge_short(segments: list[Segment]) -> list[Segment]:
    """A span shorter than MIN_DURATION is the click between two slides: it merges with the
    previous one (with the next one if it is the first), so no second of speech is orphaned."""
    result: list[Segment] = []
    for s in segments:
        if result and s.end - s.start + 1 < MIN_DURATION:
            result[-1].end = s.end
        elif result and result[-1].end - result[-1].start + 1 < MIN_DURATION:
            result[-1] = Segment(result[-1].start, s.end)
        else:
            result.append(Segment(s.start, s.end))
    return result


def _bright_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """The slide's rectangle: the widest band of bright columns, and within it the widest
    band of bright rows. Rows are counted only across the slide's columns: in a video wider
    than the slide (20:9 from a phone, the slide in 4:3 with black bars beside it) a line of
    text would leave less than half of the full frame bright, and the slide would split at
    its empty part."""
    bright = np.asarray(img.convert("L")) > 60
    columns = bright.mean(axis=0) > 0.5
    if not columns.any():
        return None
    x0, x1 = _widest_band(columns)
    rows = bright[:, x0:x1].mean(axis=1) > 0.5
    if not rows.any():
        return None
    y0, y1 = _widest_band(rows)
    return x0, y0, x1, y1


def _widest_band(mask: np.ndarray) -> tuple[int, int]:
    best, start = (0, 0, 0), None
    for i, v in enumerate([*mask, False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > best[0]:
                best = (i - start, start, i)
            start = None
    return best[1], best[2]


def _dhash(img: Image.Image, side: int = 16) -> np.ndarray:
    """Difference hash: each bit says whether a pixel is brighter than its left neighbor.
    Insensitive to brightness and compression, sensitive to different text."""
    g = np.asarray(img.convert("L").resize((side + 1, side), Image.LANCZOS), dtype=np.int16)
    return (g[:, 1:] > g[:, :-1]).flatten()


def _ffmpeg(*args: str, duration: float = 0.0, on_progress: Optional[Callable[[float], None]] = None) -> None:
    """ffmpeg, quietly. With `on_progress`, at every ffmpeg update (-progress) the fraction of
    `duration` already processed. Progress and errors come through a single pipe: with two,
    an ffmpeg that filled the error pipe while the other one is being read would stall
    forever. The "key=value" lines are the progress; the others are ffmpeg messages, and if
    it fails the error carries the last ones."""
    command = ["ffmpeg", "-v", "error", "-y", *(["-progress", "pipe:1", "-nostats"] if on_progress else []), *args]
    messages: deque[str] = deque(maxlen=4)
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace") as process:
        for line in process.stdout:
            key, equals, value = line.strip().partition("=")
            if not (equals and key.isidentifier()):
                messages.append(line.strip())
            elif on_progress and key == "out_time_us" and value.isdigit() and duration > 0:
                on_progress(min(1.0, int(value) / 1e6 / duration))
    if process.returncode:
        raise RuntimeError(f"ffmpeg exited with {process.returncode}: {' · '.join(m for m in messages if m)}")
