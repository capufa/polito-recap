"""A lecture's processing, from start to finish: the steps in a row, the ones already done
skipped. It is the core of the program: the app's queue (jobs.py) runs it for every lecture in
a separate process, which can be stopped at any point,

    python -m recap.processing COURSES COURSE LECTURE

and it reports how far along it is through a Progress: one JSON line per event, which the
app's Job reads. The steps, with their names and weights, are in jobs.STEPS.

A lecture is a video with the slides on screen (.mp4) or just the voice (.mp3). With the video,
the screen tells which slide was up at every instant; with the audio it does not: the model
gets all the slides, with the whole speech, and matches them itself by topic.

The slow steps — audio, frames, transcription, report — are skipped if their file already
exists, and each one writes its file only when it has finished: an interrupted lecture (a
restart, a blackout) resumes where it was. Alignment, page and indexes are always redone: they
cost a minute.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Callable, TextIO

from . import alignment, check, ocr, page, report, transcription, video
from .page import indexes
from .slides import Deck
from .storage import Lecture, read_json, write_json
from .timecode import hhmmss

ALREADY_DONE = "already done"
AUDIO_ONLY = "audio only: no screen"


def process(lecture: Lecture, progress: Progress) -> None:
    """Makes (or finishes) the lecture, with its file and slides already in its folder, and
    rebuilds the indexes."""
    decks = [Deck(pdf) for pdf in lecture.pdfs()]
    duration = video.duration(lecture.media)

    _slow(progress, "audio", lecture.audio.exists(),
          lambda on_progress: video.extract_audio(lecture.media, lecture.audio, duration, on_progress))
    if lecture.audio_only:
        progress.finish("frames", AUDIO_ONLY)
    else:
        _slow(progress, "frames", lecture.frames.exists(),
              lambda on_progress: video.extract_frames(lecture.media, lecture.frames, duration, on_progress))

    def transcribe(on_progress: Callable[[float], None]) -> None:
        prompt = transcription.prompt_from_slides(lecture.course, [p for d in decks for p in d.pages])
        write_json(lecture.transcript, transcription.transcribe(lecture.audio, prompt, lecture.language, on_progress))
    _slow(progress, "transcription", lecture.transcript.exists(), transcribe)
    transcript = read_json(lecture.transcript)

    progress.start("alignment")
    meta = {"course": lecture.course, "file": lecture.media.name, "duration": hhmmss(duration),
            "audio_only": lecture.audio_only, "decks": [d.name for d in decks], "language": lecture.language}
    if lecture.audio_only:
        aligned = alignment.audio_only(decks, transcript, meta)
        progress.finish("alignment", "audio only: the model matches the slides by topic")
    else:
        aligned = _align(lecture, decks, transcript, meta, progress)
    write_json(lecture.alignment, aligned)

    _slow(progress, "report", lecture.report.exists(),
          lambda _: write_json(lecture.report, report.generate(aligned)))
    progress.start("page")
    page.write(lecture)
    progress.finish("page")
    progress.start("indexes")
    indexes.write(lecture.courses)
    progress.finish("indexes")


def _align(lecture: Lecture, decks: list[Deck], transcript: list[dict], meta: dict,
           progress: Progress) -> dict:
    """With the video: which slide was on screen, and what the lecturer was saying meanwhile.
    Screens without a slide are read with OCR (from the full frame at the segment's middle
    second, which the page then shows), and that is the long part of the step."""
    box = video.slide_box(lecture.frames)
    segments = video.visual_segments(lecture.frames, box)
    matches = alignment.match(segments, decks, lecture.frames, box)
    off_slide = [i for i, m in enumerate(matches) if m.page is None]
    screen_texts = {}
    for n, i in enumerate(off_slide, 1):
        screen_texts[i] = ocr.read(video.screen(lecture, matches[i].segment.center))
        progress.progress("alignment", n / len(off_slide))
    aligned = alignment.build(matches, transcript, screen_texts, meta)
    check.write(matches, decks, screen_texts, lecture)
    progress.finish("alignment", f"{len(segments)} segments: {len(segments) - len(off_slide)} with a slide, "
                                 f"{len(off_slide)} read with OCR")
    return aligned


def _slow(progress: Progress, step: str, done: bool,
          action: Callable[[Callable[[float], None]], None]) -> None:
    """A slow step: skipped if its file already exists; otherwise done, with its percentage."""
    if done:
        progress.finish(step, ALREADY_DONE)
        return
    progress.start(step)
    action(lambda fraction: progress.progress(step, fraction))
    progress.finish(step)


class Progress:
    """How the processing is going, for the app's Job: every event is a JSON line on the
    channel the Job reads, ["progress", "audio", 0.5]; an error is ["error", message]. A
    skipped step goes straight to finish, with a note saying why."""

    def __init__(self, channel: TextIO):
        self._channel = channel

    def send(self, *event) -> None:
        print(json.dumps(event, ensure_ascii=False), file=self._channel, flush=True)

    def start(self, step: str) -> None:
        self.send("start", step)

    def progress(self, step: str, fraction: float) -> None:
        self.send("progress", step, fraction)

    def finish(self, step: str, note: str = "") -> None:
        self.send("finish", step, note)


def _in_process(courses: Path, course: str, name: str) -> None:
    """The lecture in its own process. The event channel is the real stdout; everything else
    that would end up on stdout, even from C libraries, goes to stderr, that is to the logs:
    the channel stays clean. On an error: the traceback in the logs, the message on the
    channel, exit code 1."""
    progress = Progress(os.fdopen(os.dup(1), "w", encoding="utf-8"))
    os.dup2(2, 1)
    try:
        process(Lecture.find(courses, course, name), progress)
    except Exception as error:
        traceback.print_exc()
        progress.send("error", str(error) or type(error).__name__)
        sys.exit(1)


if __name__ == "__main__":
    _in_process(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
