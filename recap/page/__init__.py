"""
The lecture page: report.json + alignment.json → lecture.html, a single file.

WHY A FIXED TEMPLATE
    The model writes the content (report.json); this module lays it out, always the same
    way, and never calls it: every lecture looks the same. Both JSON files are needed:
    the timestamps of each slide live in the alignment, not in the report. The page is made
    only from the lecture's files (the JSONs, the slides, and the screens, which are
    extracted again from the video if missing): it is rebuilt when the lecture's title or
    the course's name changes.

    Here the content (the HTML of the sections) and the frame shared by every page
    (document, link, breadcrumbs_html); next to it, as real files, style.css
    (colors and shapes, light and dark theme, for every page) and lecture.js (what moves
    on the lecture page). The indexes — home and courses — live in indexes.py, with index.js.

A SINGLE FILE
    Style, script and images (slides and screens, JPEG in base64) are inside the page: it
    opens with a double click, offline too and on another device. The lecture's file
    (video or audio) is not: it sits next to the page and is linked by name, so the
    lecture folder moves as a block; where it is missing (the phone, an email) the page
    works anyway, without a player.

WHAT'S IN IT
    sections     1. Lecture (summary + one card per slide, grouped by deck),
                 2. Off the slides, 3. Exam, 4. Notices, then the notes
    path         at the top of the side, "⌂ Courses / course": the home and the course index
    interaction  every timestamp — in the fields and inside the texts — takes the player
                 to that instant; under the player: 5 s back, pause, 5 s forward (also
                 with the ← → arrows) and the speed; the player always stays within reach,
                 at the side or, in narrow windows, docked in a corner. Video only: while
                 it plays, the card of what is on screen lights up and "Follow the video"
                 keeps it in view, and a summary point leads to its card. Then text
                 search; a "Studied" tick per slide; light or dark theme; Ctrl+P prints
                 everything expanded. Ticks, theme and speed stay saved in the browser.
    doubts       an exam or notice item whose quote is not in the transcript, or whose
                 timestamp falls where nobody speaks, carries the "to check" mark
                 (report.Quotes); so does a slide or a segment that the report names and
                 the lecture does not have
"""
from __future__ import annotations

import base64
import html
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from ..report import Quotes
from ..slides import Deck
from ..storage import Lecture, atomic, read_json
from ..timecode import readable, seconds
from ..video import Segment, screen

HERE = Path(__file__).resolve().parent
SLIDE_DPI = 110            # rendered larger and scaled down: the text stays sharp
IMAGE_WIDTH = 900          # px: the thumbnail shows at 220, enlarged up to this
JPEG_QUALITY = 70

_e = html.escape
_TIMESTAMP = re.compile(r"\b\d{2}:\d{2}:\d{2}\b")
_NONE = '<p class="none">None.</p>'
_OCR_CAVEAT = ('<p class="caveat">No PDF slide was on screen here: the on-screen text was read from '
               'the video with OCR, and what was said comes from the transcript.</p>')

# The player controls' icons: drawn in the text color (style.css, .controls svg).
_BACK_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12a8 8 0 1 0 2.3-5.6"/><path d="M4 4v4.5h4.5"/></svg>'
_FORWARD_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v4.5h-4.5"/></svg>'
_PLAY_ICON = '<svg class="icon-play" viewBox="0 0 24 24" aria-hidden="true"><path class="filled" d="M8 5.5v13l10.5-6.5z"/></svg>'
_PAUSE_ICON = ('<svg class="icon-pause" viewBox="0 0 24 24" aria-hidden="true">'
               '<path class="filled" d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>')
_COLLAPSE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'
# The home's house, at the start of every "⌂ Courses / …" path (style.css, .breadcrumbs svg).
HOME_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/>'
             '<path d="M5.5 9v11h13V9"/><path d="M10 20v-5.5h4V20"/></svg>')

# What the browser saves (ticks, theme, speed; saved.js) lives under this prefix: the app's
# old name, kept so that the ticks already saved in browsers are not lost.
STORAGE_PREFIX = "appunti:"
# In the <head>, before painting: the storage prefix for every script, the theme picked last
# time, and the "js" mark: style.css hides the cards for their entrance animation only under
# it, so without JavaScript they stay visible.
_BOOT = (f'var STORAGE_PREFIX={json.dumps(STORAGE_PREFIX)};document.documentElement.classList.add("js");'
         'try{var t=JSON.parse(localStorage.getItem(STORAGE_PREFIX+"theme"));'
         'if(t)document.documentElement.dataset.theme=t}catch(e){}')
# How many slides are ticked "Studied": on the lecture page and on every lecture of the
# indexes, filled in by saved.js.
STUDY_PROGRESS = '<div class="progress"><div class="bar"><i></i></div><span class="progress-text"></span></div>'


@dataclass
class _Section:
    id: str
    number: str        # empty for the notes, which are not one of the four sections
    title: str
    count: int
    label: tuple[str, str] | None     # singular and plural under the number in the tiles at the top; notes have no tile
    body: str


def write(lecture: Lecture) -> None:
    """lecture.html in the lecture folder, from its files: report, alignment, transcript,
    slides, and the screen of every off-slide segment the report covers."""
    report = read_json(lecture.report)
    alignment = read_json(lecture.alignment)
    quotes = Quotes(read_json(lecture.transcript))
    slide_spans = {(s["deck"], s["page"]): s["intervals"] for s in alignment["slides"]}
    off_slide_ends = {f["from"]: f["to"] for f in alignment["off_slide"]}
    by_name = {d.name: d for d in (Deck(pdf) for pdf in lecture.pdfs())}
    sections = [
        _Section("lecture", "1", "Lecture", len(report["slides"]), ("slide explained", "slides explained"),
                 _summary(report["summary"], to_card=not lecture.audio_only)
                 + _slide_cards(report["slides"], slide_spans, by_name)),
        _Section("off-slide", "2", "Off the slides", len(report["off_slide"]),
                 ("segment without slides", "segments without slides"),
                 _off_slide_cards(report["off_slide"], off_slide_ends, lecture)),
        _Section("exam", "3", "Exam", len(report["exam"]), ("exam item", "exam items"),
                 _callouts(report["exam"], quotes)),
        _Section("notices", "4", "Notices", len(report["notices"]), ("notice", "notices"),
                 _callouts(report["notices"], quotes)),
        _Section("notes", "", "Notes", len(report["notes"]), None, _notes(report["notes"])),
    ]
    with atomic(lecture.page) as partial:        # the page exists = the lecture is finished: whole or nothing
        partial.write_text(_page(report["title"], alignment["lecture"], sections, lecture), encoding="utf-8")


def _page(title: str, meta: dict, sections: list[_Section], lecture: Lecture) -> str:
    title, course = _e(title), _e(lecture.course)
    toc, tiles, body = [], [], []
    for s in sections:
        toc.append(f'<a href="#{s.id}" class="tone-{s.id}">{_e(s.title)}<span class="n">{s.count}</span></a>')
        number = f'<span class="num">{s.number}</span>' if s.number else ""
        body.append(f'<section id="{s.id}" class="section tone-{s.id}"><h2>{number}{_e(s.title)}</h2>'
                    f'{s.body}</section>')
        if s.label:
            tiles.append(f'<a href="#{s.id}" class="tile tone-{s.id}"><b>{s.count}</b>'
                         f'<span>{_e(plural(s.count, *s.label))}</span></a>')
    file_name = _e(lecture.media.name)
    above = " · ".join([course, file_name, readable(seconds(meta["duration"])), _e(", ".join(meta["decks"]))])
    crumbs = breadcrumbs_html([("Courses", link(lecture.root, lecture.home_index)),
                               (lecture.course, link(lecture.root, lecture.course_index))])
    # The player: the video, or the audio for a voice-only lecture. With audio there is no
    # screen to follow: no "Follow the video", no check grid.
    tag = "audio" if lecture.audio_only else "video"
    follow = "" if lecture.audio_only else '<label class="follow"><input type="checkbox" id="follow"> Follow the video</label>'
    side = (f'<div class="brand">{crumbs}<b>{title}</b></div>'
            f'{STUDY_PROGRESS}'
            f'<div class="player"><div class="frame"><{tag} id="media" src="{_e(quote(lecture.media.name))}" '
            f'controls preload="metadata"></{tag}><span id="jump" class="jump" aria-hidden="true"></span></div>'
            '<div class="controls">'
            f'<button id="back" type="button" aria-label="Back 5 seconds" title="Back 5 seconds (← arrow)">'
            f'{_BACK_ICON}5 s</button>'
            f'<button id="play" type="button" aria-label="Play">{_PLAY_ICON}{_PAUSE_ICON}</button>'
            f'<button id="forward" type="button" aria-label="Forward 5 seconds" title="Forward 5 seconds (→ arrow)">'
            f'5 s{_FORWARD_ICON}</button>'
            f'<button id="collapse" type="button" title="Collapse the player" aria-expanded="true">'
            f'{_COLLAPSE_ICON}</button></div>'
            '<div class="speed"><label for="speed">Speed</label>'
            '<input id="speed" type="range" min="0.5" max="2" step="0.25" value="1">'
            f'<button id="speed-value" type="button" title="Back to 1×">1×</button></div>{follow}</div>'
            f'<p class="media-missing">File not found: <code>{file_name}</code> must be in the same '
            'folder as the page. The page works anyway, without a player.</p>'
            '<div class="search"><input id="search" type="search" placeholder="Search the notes" autocomplete="off">'
            '<span id="matches" aria-live="polite"></span></div>'
            f'<nav class="toc">{"".join(toc)}</nav>'
            '<button id="theme" class="theme" type="button">Light / dark</button>')
    header = (f'<header class="reveal"><p class="meta">{above}</p><h1>{title}</h1>'
              f'<div class="tiles">{"".join(tiles)}</div></header>')
    check = link(lecture.root, lecture.check)
    footer = ("" if lecture.audio_only else
              f'<footer class="footer">To check the matches between video and slides: '
              f'<a href="{check}">{check}</a>.</footer>')
    # The page's language is the lecture's: nearly all of it is the notes, in that language.
    return document(title, f'<div class="layout">\n<aside class="side">{side}</aside>\n'
                           f'<main class="main">{header}{"".join(body)}{footer}</main>\n</div>\n'
                           '<div class="lightbox" id="lightbox" hidden><img alt=""></div>',
                    scripts=("saved.js", "lecture.js"), attributes=f' data-key="{_e(lecture.key)}"',
                    lang=meta["language"])


def document(title: str, body: str, *, scripts: tuple[str, ...], attributes: str = "", lang: str = "en") -> str:
    """A whole page, a single file: style.css and the given scripts inside, and the saved
    theme applied before painting. `title` and `body` arrive already as HTML."""
    style = (HERE / "style.css").read_text(encoding="utf-8")
    code = "".join(f"<script>\n{(HERE / s).read_text(encoding='utf-8')}</script>\n" for s in scripts)
    return (f'<!doctype html>\n<html lang="{_e(lang)}">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{title}</title>\n<style>\n{style}</style>\n<script>{_BOOT}</script>\n</head>\n'
            f'<body{attributes}>\n{body}\n{code}</body>\n</html>\n')


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def slide_id(slide: dict) -> str:
    """How a slide of the report is known to its "Studied" tick: deck:page."""
    return f'{slide["deck"]}:{slide["page"]}'


def link(start: Path, target: Path) -> str:
    """The relative link from the folder `start` to the file `target`: the pages move together
    with the courses/ folder and stay linked."""
    return quote(Path(os.path.relpath(target, start)).as_posix())


def breadcrumbs_html(stops: list[tuple[str, str | None]]) -> str:
    """The path "⌂ Courses / course / …": every stop with its link, the last one without if
    it is the current page."""
    parts = []
    for i, (name, href) in enumerate(stops):
        text = (HOME_ICON if i == 0 else "") + _e(name)
        parts.append(f'<a href="{href}">{text}</a>' if href else f'<span>{text}</span>')
    return '<nav class="breadcrumbs">' + '<span class="sep">/</span>'.join(parts) + "</nav>"


def _summary(points: list[dict], *, to_card: bool) -> str:
    """The points in time order, each with its timestamp. With video a point leads to the card
    of that moment; with audio the cards have no segments, and the point is just text."""
    if not points:
        return ""
    def point(p: dict) -> str:
        if not to_card:
            return f"<span>{_e(p['point'])}</span>"
        return (f'<button class="goto" type="button" data-s="{seconds(p["t"])}" title="Go to its card">'
                f'{_e(p["point"])}</button>')
    rows = "".join(f'<li class="entry">{_timestamp(p["t"])}{point(p)}</li>' for p in points)
    return f'<div class="summary reveal"><h3>Summary</h3><ol>{rows}</ol></div>'


def _slide_cards(slides: list[dict], spans: dict[tuple[str, int], list[dict]], decks: dict[str, Deck]) -> str:
    """One card per slide, in the report's order, with a heading at every change of deck.
    A slide without segments is there anyway (in a voice-only lecture none has any); a
    slide the lecture does not have at all carries the "to check" mark."""
    if not slides:
        return _NONE
    out, deck = [], None
    for s in slides:
        if s["deck"] != deck:
            deck = s["deck"]
            out.append(f'<div class="deck">{_e(deck)}</div>')
        when = spans.get((s["deck"], s["page"]))
        if when is not None and s["deck"] not in decks:
            raise FileNotFoundError(f"The slides “{s['deck']}.pdf” are missing from the lecture.")
        out.append(_card(
            image=None if when is None else _jpeg(decks[s["deck"]].render(s["page"], SLIDE_DPI, color=True)),
            alt=f'Page {s["page"]} of {s["deck"]}',
            heading=f'<span class="page-no">p{s["page"]}</span><h3>{_e(s["title"])}</h3>',
            spans=when, points=s["key_points"], explanation=s["explanation"],
            studied=slide_id(s),
            doubt="slide not in the lecture" if when is None else None))
    return "".join(out)


def _off_slide_cards(items: list[dict], ends: dict[str, str], lecture: Lecture) -> str:
    """One card per segment without slides, with the screen as it was at the segment's middle
    second (the one OCR read; if missing, it is extracted again from the video)."""
    if not items:
        return _NONE
    cards = []
    for f in items:
        to = ends.get(f["from"])
        image = None
        if to:
            with Image.open(screen(lecture, Segment.from_span({"from": f["from"], "to": to}).center)) as frame:
                image = _jpeg(frame)
        cards.append(_card(
            image=image, alt=f'The screen at {f["from"]}', heading=f'<h3>{_e(f["shows"])}</h3>',
            spans=[{"from": f["from"], "to": to}] if to else None, points=[], explanation=f["explanation"],
            studied=None, doubt=None if to else "segment not in the lecture"))
    return _OCR_CAVEAT + "".join(cards)


def _card(*, image: str | None, alt: str, heading: str, spans: list[dict] | None, points: list[str],
          explanation: str, studied: str | None, doubt: str | None) -> str:
    """Image on the left; title, timestamps, key points and explanation (expanded on request) on the right."""
    classes = "card entry reveal" + ("" if image else " no-image")
    intervals = ",".join(f'{seconds(t["from"])}-{seconds(t["to"])}' for t in spans or [])
    attribute = f' data-intervals="{intervals}"' if intervals else ""
    thumb = (f'<button class="thumb" type="button" aria-label="Enlarge: {_e(alt)}"><img src="{image}" '
             f'alt="{_e(alt)}" decoding="async"></button>') if image else ""
    tick = (f'<label class="tick"><input type="checkbox" data-id="{_e(studied)}"><span>Studied</span>'
            '</label>') if studied else ""
    times = "".join(_timestamp(t["from"], label=f'{t["from"]} → {t["to"]}') for t in spans or [])
    times = f'<div class="times">{times}</div>' if times else ""
    bullets = "".join(f"<li>{_text(p)}</li>" for p in points)
    bullets = f'<ul class="key-points">{bullets}</ul>' if bullets else ""
    text = (f'<div class="explanation clamped">{_paragraphs(explanation)}</div>'
            '<button class="expand" type="button" aria-expanded="false">Read more</button>'
            ) if explanation.strip() else ""
    return (f'<article class="{classes}"{attribute}>{thumb}<div class="card-body">'
            f'<div class="title-row">{heading}{_doubt(doubt)}{tick}</div>{times}{bullets}{text}</div></article>')


def _callouts(items: list[dict], quotes: Quotes) -> str:
    """Exam items or notices in timestamp order, with the lecturer's exact words; exam items with their kind."""
    if not items:
        return _NONE
    rows = []
    for v in sorted(items, key=lambda v: v["t"]):
        kind = f'<span class="kind">{_e(v["kind"])}</span>' if "kind" in v else ""
        rows.append(f'<li class="callout entry reveal">{_timestamp(v["t"])}<div>{kind}'
                    f'<p class="callout-text">{_text(v["text"])}{_doubt(quotes.problem(v))}</p>'
                    f'<blockquote>“{_e(v["quote"])}”</blockquote></div></li>')
    return '<ul class="callouts">' + "".join(rows) + "</ul>"


def _notes(notes: list[str]) -> str:
    if not notes:
        return _NONE
    return '<ul class="notes">' + "".join(f'<li class="entry">{_text(n)}</li>' for n in notes) + "</ul>"


def _timestamp(t: str, label: str | None = None, inline: bool = False) -> str:
    """A button that takes the player to t; it shows t, or the label (a whole span)."""
    classes = "t inline" if inline else "t"
    return f'<button class="{classes}" type="button" data-s="{seconds(t)}">{_e(label or t)}</button>'


def _text(text: str) -> str:
    """The model's text, with every timestamp (HH:MM:SS) taking the player to that instant."""
    parts, start = [], 0
    for m in _TIMESTAMP.finditer(text):
        parts += [_e(text[start:m.start()]), _timestamp(m.group(), inline=True)]
        start = m.end()
    return "".join(parts) + _e(text[start:])


def _doubt(reason: str | None) -> str:
    return f'<span class="unverified">to check: {_e(reason)}</span>' if reason else ""


def _paragraphs(text: str) -> str:
    return "".join(f"<p>{_text(line.strip())}</p>" for line in text.splitlines() if line.strip())


def _jpeg(img: Image.Image) -> str:
    """The image as a JPEG data URI, at most IMAGE_WIDTH wide."""
    img = img.convert("RGB")
    if img.width > IMAGE_WIDTH:
        img = img.resize((IMAGE_WIDTH, round(img.height * IMAGE_WIDTH / img.width)), Image.LANCZOS)
    data = io.BytesIO()
    img.save(data, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(data.getvalue()).decode("ascii")
