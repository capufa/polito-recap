"""The grid for checking by eye: every span of the video next to the page it was matched
with, and the score. A wrong match shows in a second.

The grid, the frames and the previews all live in work/: the images are linked with paths
relative to work/ (page.link), and stay right if the lecture folder moves."""
from __future__ import annotations

import html

from .alignment import Match
from .page import link
from .slides import Deck
from .storage import Lecture, atomic
from .video import frame_path

PREVIEW_DPI = 60


def write(matches: list[Match], decks: list[Deck], screen_texts: dict[int, str],
          lecture: Lecture) -> None:
    """check.html, with the page previews next to the frames."""
    lecture.previews.mkdir(exist_ok=True)
    by_name = {d.name: d for d in decks}
    rows = []
    for i, m in enumerate(matches):
        frame = link(lecture.work, frame_path(lecture.frames, m.segment.center))
        span = m.segment.span
        when = f"{span['from']} → {span['to']}"
        if m.page is None:
            right = f"<pre>{html.escape(screen_texts.get(i, '')[:600])}</pre>"
            title = f"<b class=off>OFF-SLIDE</b> (best {m.score:.2f})"
        else:
            png = lecture.previews / f"{m.page.deck}-p{m.page.number:02d}.png"
            if not png.exists():
                with atomic(png) as partial:
                    by_name[m.page.deck].render(m.page.number, PREVIEW_DPI).save(partial)
            right = f'<img src="{link(lecture.work, png)}">'
            title = (f"{html.escape(m.page.deck)} p{m.page.number} — {html.escape(m.page.title)} "
                     f"({m.score:.2f})")
        rows.append(f'<tr><td class=n>#{i + 1}<br>{when}</td><td><img src="{frame}"></td>'
                    f"<td>{right}</td><td>{title}</td></tr>")
    document = ("<!doctype html><meta charset=utf-8><title>Match check</title>"
                "<style>body{font:14px system-ui;margin:16px} table{border-collapse:collapse}"
                "td{border-bottom:1px solid #ccc;padding:6px;vertical-align:top} img{width:360px}"
                "pre{width:360px;white-space:pre-wrap;font-size:11px} .n{white-space:nowrap} .off{color:#c00}</style>"
                f"<h1>Frame ↔ matched page</h1><table>{''.join(rows)}</table>")
    lecture.check.write_text(document, encoding="utf-8")
