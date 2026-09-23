"""The indexes: the home with the courses (courses/index.html) and, for every course, its
lectures (courses/<course>/index.html). They are rebuilt at every app start, at every course
created, renamed or deleted, and at every lecture processed, deleted or retitled, reading
what is on disk: the courses are the folders, the lectures the ones with the page.

Every lecture shows title, duration, how many slides, exam items and notices, and how many
slides are already ticked "Studied" (index.js reads it from the browser, where the ticks
live). The links are relative: the courses/ folder moves as a whole and stays linked.

The indexes also add and remove (manage.js, which talks to the app): on the home the "+"
for a new course, in the course the zone to drop the lecture file and the slides onto, and
the jobs in progress; next to every course the ✎ that renames it, next to every lecture the
one that changes its title, and next to both the 🗑, which sends them to the trash.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from ..storage import AUDIO, FORMATS, INDEX, LANGUAGES, PDF, TRASH_DAYS, VIDEO, Lecture, list_courses, read_json
from ..timecode import readable, seconds
from . import STUDY_PROGRESS, breadcrumbs_html, document, link, plural, slide_id

_e = html.escape
_TRASH = f'data-trash-days="{TRASH_DAYS}"'     # for manage.js's confirmation texts
_SCRIPTS = ("saved.js", "index.js", "manage.js")
_NEW_COURSE = ('<div class="add" id="new-course"><button class="add-open" type="button">'
               '+ New course</button><form hidden><input name="course" placeholder="Course name, e.g. '
               'Calculus 1" autocomplete="off" maxlength="80"><button class="button primary" type="submit">'
               'Create</button><button class="button cancel" type="button">Cancel</button></form>'
               '<p class="error-message" role="alert"></p></div>')


@dataclass
class _Entry:
    lecture: Lecture
    title: str
    duration: int      # seconds
    slides: list[str]  # the ids of its slides, to count its "Studied" ticks
    exam: int
    notices: int
    language: str      # the lecture's, for its title

    @classmethod
    def read(cls, lecture: Lecture) -> _Entry:
        report = read_json(lecture.report)
        meta = read_json(lecture.alignment)["lecture"]
        return cls(lecture, report["title"], seconds(meta["duration"]), [slide_id(s) for s in report["slides"]],
                   len(report["exam"]), len(report["notices"]), meta["language"])


def write(courses: Path) -> None:
    """The home and the index of every course, empty ones too."""
    by_course = {c: [_Entry.read(lecture) for lecture in Lecture.of_course(courses, c) if lecture.finished]
                 for c in list_courses(courses)}
    for course, entries in by_course.items():
        _course_index(courses, course, entries)
    (courses / INDEX).write_text(_home(courses, by_course), encoding="utf-8")


def _home(courses: Path, by_course: dict[str, list[_Entry]]) -> str:
    items = "".join(
        f'<li class="with-actions"><a class="index-card" href="{link(courses, courses / c / INDEX)}">'
        f'<small>{_overview(entries)}</small><b>{_e(c)}</b>'
        f'{_stats(sum(e.exam for e in entries), sum(e.notices for e in entries))}</a>'
        f'{_actions("course", c, "Rename the course", "Delete the course", course=c)}</li>'
        for c, entries in by_course.items())
    empty = "" if by_course else '<p class="none">No courses yet.</p>'
    lectures = sum(len(entries) for entries in by_course.values())
    body = (f'<main class="sheet" {_TRASH}>{breadcrumbs_html([("Courses", None)])}<h1>Courses</h1>'
            '<p class="update" id="update" hidden></p>'
            f'<p class="meta">{_count(len(by_course), "course", "courses")} · '
            f'{_count(lectures, "lecture", "lectures")}</p>{empty}'
            f'<ul class="index-cards">{items}<li>{_NEW_COURSE}</li></ul></main>')
    return document("PoliTo Recap", body, scripts=_SCRIPTS)


def _course_index(courses: Path, course: str, entries: list[_Entry]) -> None:
    here = courses / course
    page = here / INDEX
    items = "".join(_lecture_item(here, e) for e in entries)
    listing = f'<ul class="index-cards">{items}</ul>' if items else '<p class="none">No lectures yet.</p>'
    body = (f'<main class="sheet" {_TRASH}>'
            f'{breadcrumbs_html([("Courses", link(here, courses / INDEX)), (course, None)])}'
            f'<h1>{_e(course)}</h1><p class="meta">{_overview(entries)}</p>'
            f'{_upload(course)}<section id="jobs" data-course="{_e(course)}" hidden>'
            '<h2>In progress</h2><p class="error-message" role="alert"></p><ul class="job-list"></ul></section>'
            f'<h2>Lectures</h2>{listing}</main>')
    page.write_text(document(_e(course), body, scripts=_SCRIPTS), encoding="utf-8")


def _lecture_item(here: Path, e: _Entry) -> str:
    """A lecture in the course list: in gray the file name and the numbers, in bold the title,
    then the stats and the study progress; next to it the ✎ (the title) and the 🗑."""
    actions = _actions("lecture", e.title, "Retitle the lecture", "Delete the lecture",
                       course=e.lecture.course, lecture=e.lecture.name)
    return (f'<li class="with-actions"><a class="index-card lecture" href="{link(here, e.lecture.page)}" '
            f'data-key="{_e(e.lecture.key)}" data-ids="{_e(json.dumps(e.slides))}">'
            f'<small>{_e(e.lecture.name)} · {"audio" if e.lecture.audio_only else "video"} · '
            f'{readable(e.duration)} · {_count(len(e.slides), "slide", "slides")}</small>'
            f'<b lang="{_e(e.language)}">{_e(e.title)}</b>{_stats(e.exam, e.notices)}{STUDY_PROGRESS}</a>{actions}</li>')


def _actions(kind: str, name: str, edit: str, delete: str, **data) -> str:
    """The ✎ and the 🗑 next to a course or a lecture (outside the link: they can't go inside),
    with the data manage.js needs: the name the user reads (the course's, or the lecture's
    title), to offer in the ✎ and to quote in the 🗑's confirmation, and where it lives."""
    attributes = " ".join(f'data-{k}="{_e(str(v))}"' for k, v in {"name": name, **data}.items())
    return (f'<span class="entry-actions">'
            f'<button type="button" data-edit="{kind}" {attributes} aria-label="{edit} {_e(name)}" '
            f'title="{edit}">✎</button>'
            f'<button type="button" data-delete="{kind}" {attributes} aria-label="{delete} {_e(name)}" '
            f'title="{delete}">🗑</button></span>')


def _upload(course: str) -> str:
    """The zone for a new lecture: the lecture file and the slides, dropped or picked, and the
    language the lecturer speaks."""
    accept = ",".join((*FORMATS, PDF))
    languages = "".join(f'<option value="{code}">{_e(name)}</option>' for code, name in LANGUAGES.items())
    return (f'<section id="upload" data-course="{_e(course)}" data-video="{VIDEO}" '
            f'data-audio="{AUDIO}" data-pdf="{PDF}"><h2>New lecture</h2>'
            f'<label class="dropzone"><input type="file" multiple accept="{accept}">'
            f'<b>Drop the lecture and the slides here</b>'
            f'<span>the {VIDEO} video or the {AUDIO} audio, and the PDF slides: both are needed · '
            'or click to pick them</span></label>'
            '<ul class="chosen"></ul><p class="error-message" role="alert"></p>'
            f'<div class="submit-row"><label class="language">Language <select>{languages}</select></label>'
            '<button class="button primary process" type="button">▶ Process lecture</button>'
            '<button class="button stop" type="button" hidden>Cancel</button>'
            '<span class="upload-status" aria-live="polite"></span></div></section>')


def _overview(entries: list[_Entry]) -> str:
    return f'{_count(len(entries), "lecture", "lectures")} · {readable(sum(e.duration for e in entries))}'


def _stats(exam: int, notices: int) -> str:
    return (f'<span class="stats"><span class="tone-exam">{_count(exam, "exam item", "exam items")}</span> · '
            f'<span class="tone-notices">{_count(notices, "notice", "notices")}</span></span>')


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {plural(n, one, many)}"
