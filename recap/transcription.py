"""Transcription: voice → text with timestamps, with faster-whisper on CPU. Model,
precision and threads are settings (WHISPER_*, settings.py); the language is the lecture's,
chosen at upload.

`large-v3-turbo` int8, the default. On 10 minutes of an Italian lecture, on the 4 fast cores
of an i5-12600H: 4.7x real time and 2.1 GB peak, 4% of the words different from large-v3
(2.1x, 4.2 GB); medium 3.8x, 2.3 GB, 6%; small 8.4x, 1.3 GB, 12%. On 2 slow cores the
default still runs at 1.6x real time: the setup picks the model by memory, never by speed
(setup.py). The wrong words that remain are fixed by the report model from context and
slides: what matters here is not losing passages, and that is what the options below are
for. Threads: on an
i5-12600H (4 fast cores and 8 slow ones), 5 minutes of lecture, 4 threads 77-82 s,
5 threads 110 s, 8 threads 104 s, 16 threads 99 s: past the fast cores it slows down.

IN SLICES. Whisper computes the features of all the audio it gets in one go: a whole
82-minute lecture needs 4.4 GB, a 138-minute one 7.5 GB, more than a small home server can spare.
So it gets slices of about SLICE_SECONDS, cut in the middle of a silence: between one window
and the next it keeps no memory of the text (condition_on_previous_text=False), so the
slices do not change what it hears; in memory, besides the model and one slice, only the
whole audio stays (about 0.2 GB per hour). On the i5-12600H: 82 minutes 2.7 GB peak instead
of 4.4, 221 minutes 3.5 GB; same time (3.7x real time), 98% of the words identical, no
difference longer than 12 words. The library's batched mode (BatchedInferencePipeline) was
tried and dropped: on the same lecture it repeated a word a hundred times and lost
sentences, a notice among them.
"""
from pathlib import Path
from typing import Callable

import numpy as np
from faster_whisper import WhisperModel, decode_audio
from faster_whisper.vad import VadOptions, get_speech_timestamps

from .settings import load
from .slides import SlidePage
from .video import SAMPLE_RATE

SLICE_SECONDS = 600     # seconds of audio per slice, at most up to the first silence after

# Phrases Whisper invents over silences in Italian audio (subtitle credits seen in
# training): Italian on purpose, they are data.
HALLUCINATIONS = ("amara.org", "sottotitoli e revisione", "sottotitoli a cura")


def transcribe(wav: Path, initial_prompt: str, language: str, on_progress: Callable[[float], None]) -> list[dict]:
    """Segments [{start, end, text, words: [{word, start, end}]}], float seconds.
    A word keeps the leading space Whisper gives it: joined, they give back the sentence
    exactly as spoken, apostrophes included. At each segment, `on_progress` gets the
    fraction of audio already transcribed: segments arrive in time order."""
    settings = load()
    model = WhisperModel(settings.whisper_model, device="cpu", compute_type=settings.whisper_compute_type,
                         cpu_threads=settings.whisper_threads)
    audio = decode_audio(str(wav), sampling_rate=SAMPLE_RATE)
    duration = len(audio) / SAMPLE_RATE
    result = []
    for start, end in _slices(audio):
        offset = start / SAMPLE_RATE
        segments, _ = model.transcribe(
            audio[start:end], language=language, beam_size=5,
            vad_filter=True,                     # cuts silences: fewer hallucinations, faster
            word_timestamps=True,                # needed to split a sentence at a slide change
            condition_on_previous_text=False,    # avoids repetition loops on long audio
            initial_prompt=initial_prompt)
        for s in segments:
            on_progress(min(1.0, (offset + s.end) / duration))
            text = s.text.strip()
            if any(h in text.lower() for h in HALLUCINATIONS):
                continue
            result.append({"start": _seconds(offset + s.start), "end": _seconds(offset + s.end), "text": text,
                           "words": [{"word": w.word, "start": _seconds(offset + w.start),
                                      "end": _seconds(offset + w.end)} for w in s.words or []]})
    return result


def _slices(audio: np.ndarray) -> list[tuple[int, int]]:
    """(start, end) in samples: slices of at least SLICE_SECONDS, each cut in the middle of
    the first silence that follows (Whisper's VAD: silences of 2 seconds and up)."""
    speech = get_speech_timestamps(audio, VadOptions(), sampling_rate=SAMPLE_RATE)
    slices, start = [], 0
    for before, after in zip(speech, speech[1:]):
        if before["end"] - start >= SLICE_SECONDS * SAMPLE_RATE:
            cut = (before["end"] + after["start"]) // 2
            slices.append((start, cut))
            start = cut
    slices.append((start, len(audio)))
    return slices


def _seconds(value) -> float:
    """faster-whisper returns numpy floats: the JSON wants plain floats, to the hundredth."""
    return round(float(value), 2)


def prompt_from_slides(course: str, pages: list[SlidePage], max_chars: int = 800) -> str:
    """Whisper's initial prompt (at the start of every slice) steers spelling and
    vocabulary: the course and the slide titles are the lecture's technical lexicon,
    spelled right. Nothing around them: a sentence in one language would pull Whisper
    towards that language."""
    titles = []
    for p in pages:
        if p.title and p.title not in titles:
            titles.append(p.title)
    return (f"{course}: " + ", ".join(titles))[:max_chars]
