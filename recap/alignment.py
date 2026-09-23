"""Which slide was on screen at every moment, and what the lecturer was saying at the time.

Matching: the frame at the center of each visual segment, cropped to the slide box, and
every rendered page are reduced to the box of their non-white content (the PDF is A4 with
margins, the screen share is 4:3: same content, different borders), brought to 64x48 and
normalized; the similarity is the correlation. The most similar page wins if it clears the
threshold, or if it is clearly ahead of the second one; among near-tied candidates the one
adjacent to the previous page wins (build-up slides differ by one line). Below the
threshold the span is "off-slide".

Merging: every word of the transcript goes to the span its middle instant falls in, so a
sentence straddling a slide change is split at the right second.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .slides import Deck, SlidePage
from .storage import LANGUAGES
from .timecode import hhmmss
from .video import Segment, frame_path

THRESHOLD = 0.80
LEAD_THRESHOLD = (0.60, 0.25)    # accepted below THRESHOLD too if it leads the second one by at least this much
TIE = 0.05                       # gap below which closeness to the previous page decides
RENDER_DPI = 40
SIZE = (64, 48)
TOOLBAR = (0.20, 0.05)           # bottom-left corner of the box, covered: the viewer's controls

# What flags a possible notice in a sentence, per lecture language (storage.LANGUAGES), in the
# lowercased text. Italian: stems matched anywhere, a stem catches every inflection. English:
# whole words, or "exam" would catch every "example".
NOTICE_WORDS = {
    "it": re.compile("|".join(re.escape(w) for w in (
        "esame", "appello", "consegn", "scadenz", "progetto", "aula", "ricevimento", "annull", "sospes",
        "spostat", "recuper", "portale", "iscri", "registr", "orario", "prossima settimana",
        "settimana prossima", "prossima lezione", "laboratori"))),
    "en": re.compile(r"\b(?:exams?|midterms?|deadlines?|due (?:date|on|by)|projects?|assignments?|homework|"
                     r"submi(?:t|ssions?)|office hours?|cancel(?:l?ed)?|postponed|rescheduled|moved to|rooms?|"
                     r"portal|regist(?:er|ration)|enrol(?:l|ment)?|sign up|next (?:week|lesson|lecture|class)|labs?)\b"),
}
assert set(NOTICE_WORDS) == set(LANGUAGES), "every lecture language needs its notice words"


@dataclass
class Match:
    segment: Segment
    page: SlidePage | None      # None = off-slide
    score: float


def match(segments: list[Segment], decks: list[Deck], frames: Path,
          box: tuple[int, int, int, int]) -> list[Match]:
    pages = [(p, _fingerprint(d.render(p.number, RENDER_DPI))) for d in decks for p in d.pages]
    pages = [(p, v) for p, v in pages if v is not None]
    if not pages:
        raise ValueError("the slides have no pages to compare with the video: they are empty or nearly white")
    result: list[Match] = []
    previous: SlidePage | None = None
    for s in segments:
        frame = Image.open(frame_path(frames, s.center)).crop(box).convert("L")
        v = _fingerprint(frame, cover_toolbar=True)
        if v is None:
            result.append(Match(s, None, 0.0))
            continue
        ranked = sorted(((float(v @ pv), p) for p, pv in pages), key=lambda x: -x[0])
        best = ranked[0][0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0      # a single page: the lead is over "no similarity"
        accepted = best >= THRESHOLD or (best >= LEAD_THRESHOLD[0] and best - second >= LEAD_THRESHOLD[1])
        if not accepted:
            result.append(Match(s, None, best))
            continue
        candidates = [(score, p) for score, p in ranked if score >= best - TIE]
        if previous is not None:
            candidates.sort(key=lambda c: (c[1].deck != previous.deck, abs(c[1].number - previous.number), -c[0]))
        score, previous = candidates[0]
        result.append(Match(s, previous, score))
    return result


def build(matches: list[Match], transcript: list[dict],
          screen_texts: dict[int, str], meta: dict) -> dict:
    """alignment.json: the slides seen (with all the related speech, even when the lecturer
    comes back to them), the off-slide spans with the text read from the screen, and the
    transcript segments that contain notice words, as candidates for the report."""
    speech = _speech_per_span(matches, transcript)
    slides: dict[tuple[str, int], dict] = {}
    off_slide: list[dict] = []
    for i, m in enumerate(matches):
        span = m.segment.span
        if m.page is None:
            off_slide.append({**span, "screen_text": screen_texts.get(i, ""), "speech": speech[i]})
            continue
        key = (m.page.deck, m.page.number)
        if key not in slides:
            slides[key] = {"deck": m.page.deck, "page": m.page.number, "title": m.page.title,
                           "text": m.page.text, "intervals": [], "speech": []}
        slides[key]["intervals"].append(span)
        slides[key]["speech"].extend(speech[i])
    return {"lecture": meta, "slides": list(slides.values()), "off_slide": off_slide,
            "notice_candidates": _candidates(transcript, meta["language"])}


def audio_only(decks: list[Deck], transcript: list[dict], meta: dict) -> dict:
    """alignment.json of a lecture without video: no screen says which slide was up, so all
    the slides arrive, without speech, and all the speech together, with its minutes. The
    model is the one who matches them by topic (report/prompt.md)."""
    slides = [{"deck": p.deck, "page": p.number, "title": p.title, "text": p.text, "intervals": [], "speech": []}
              for d in decks for p in d.pages]
    return {"lecture": meta, "slides": slides, "off_slide": [],
            "speech": [{"t": hhmmss(s["start"]), "text": s["text"]} for s in transcript],
            "notice_candidates": _candidates(transcript, meta["language"])}


def _candidates(transcript: list[dict], language: str) -> list[dict]:
    """The transcript segments with notice words: candidates for the report, to classify or
    discard, not notices."""
    return [{"t": hhmmss(s["start"]), "text": s["text"]} for s in transcript
            if NOTICE_WORDS[language].search(s["text"].lower())]


def _speech_per_span(matches: list[Match], transcript: list[dict]) -> list[list[dict]]:
    """For each span, the sentences said in the meantime: [{t, text}], split at the word
    when a sentence crosses a slide change."""
    starts = [m.segment.start for m in matches]
    result: list[list[dict]] = [[] for _ in matches]
    for s in transcript:
        words = s["words"] or [{"word": s["text"], "start": s["start"], "end": s["end"]}]
        per_span: dict[int, list[dict]] = {}
        for w in words:
            i = max(0, bisect_right(starts, (w["start"] + w["end"]) / 2) - 1)
            per_span.setdefault(i, []).append(w)
        for i, group in per_span.items():
            result[i].append({"t": hhmmss(group[0]["start"]), "text": "".join(w["word"] for w in group).strip()})
    return result


def _fingerprint(img: Image.Image, cover_toolbar: bool = False) -> np.ndarray | None:
    """The non-white content, scaled to SIZE and normalized: the dot product of two
    fingerprints is their correlation."""
    a = np.asarray(img, dtype=np.float32)
    if cover_toolbar:
        a = a.copy()
        a[int(a.shape[0] * (1 - TOOLBAR[1])):, :int(a.shape[1] * TOOLBAR[0])] = 255
    ys, xs = np.where(a < 235)
    if len(xs) < 50:
        return None
    crop = Image.fromarray(a.astype(np.uint8)).crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    v = np.asarray(crop.resize(SIZE, Image.LANCZOS), dtype=np.float32).flatten()
    v -= v.mean()
    norm = np.linalg.norm(v)
    return v / norm if norm else None
