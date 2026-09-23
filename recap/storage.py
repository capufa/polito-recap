"""Where things live: the courses, the lectures inside them, and the files of each lecture.

    courses/
        index.html                    the home: all the courses
        .incoming/                    the app's uploads, until they become a lecture
        .trash/<date and time>/       what was deleted from the app, as it was: <course>/ or
                                      <course>/<lecture>/; after TRASH_DAYS days the daily
                                      check removes it (server)
        <course>/
            index.html                the course's lectures
            <lecture>/                named after the lecture's file
                lecture.html          the page to open (there once the lecture is finished)
                <lecture>.mp4         the lecture's file, a video with the slides on screen —
                  or <lecture>.mp3    or just the voice: the page finds it by name
                work/                 everything else
                    language.txt      the lecture's language (it, en), chosen at upload
                    slides/           the lecturer's PDFs
                    audio.wav         the voice, 16 kHz mono             ┐
                    frames/           one frame per second, 480 px       │ extracted: rebuilt
                    screens/          the full frame of each off-slide   │ from the lecture's file,
                                      segment (OCR and page)             │ and the backup copy on
                    previews/         the slide previews                 ┘ the NAS leaves them out
                    transcript.json   the voice, word by word with the seconds
                    alignment.json    slides and speech aligned: what the model receives
                    report.json       the model's notes (the title can be changed from the app)
                    check.html        the frame ↔ slide grid, for checking by eye

A lecture folder with its file and no lecture.html is a half-done lecture: queued or being
processed in the app; after a restart (or a blackout) it resumes where it was, because every
slow step is skipped if its file is already there. That is why every file is written whole or
not at all, and truly on disk before it takes its place (atomic).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

LECTURE_PAGE = "lecture.html"
INDEX = "index.html"
VIDEO = ".mp4"
AUDIO = ".mp3"
FORMATS = (VIDEO, AUDIO)       # a lecture is a video with the slides on screen, or just the voice
# The languages a lecture can be in, chosen at upload: the code Whisper and the page use, and
# the name the upload form shows. Each one has its notice words (alignment.NOTICE_WORDS).
LANGUAGES = {"it": "Italiano", "en": "English"}
PDF = ".pdf"
INCOMING = ".incoming"
TRASH = ".trash"
TRASH_DAYS = 30
TRASH_DATE_FORMAT = "%Y-%m-%d %H.%M.%S"   # the name of each delivery to the trash: no ":", forbidden on Windows

# Characters Windows does not accept in a file or folder name: names stay valid anywhere
# the folders are copied, a NAS or a Windows PC too.
FORBIDDEN = '<>:"/\\|?*'
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def valid_name(name: str, what: str) -> str:
    """A name that becomes a folder or file as it is: not empty, no characters Windows
    rejects, no invisible or control characters, no leading or trailing dot (hidden
    folders, ".."), no spaces at the edges, no reserved names. Otherwise ValueError, with
    the reason."""
    if (not name or name != name.strip() or name.startswith(".") or name.endswith(".") or not name.isprintable()
            or any(c in FORBIDDEN for c in name) or name.split(".")[0].upper() in RESERVED):
        raise ValueError(f'{what} “{name}” is not a valid folder name: no {FORBIDDEN}, '
                         "no invisible characters, no dot at the start or end, no spaces at the edges.")
    return name


def list_courses(courses: Path) -> list[str]:
    """The courses: the folders inside courses/, in alphabetical order."""
    return sorted(d.name for d in courses.iterdir() if d.is_dir() and not d.name.startswith("."))


def course_dir(courses: Path, name: str) -> Path:
    """The folder of a course that exists; otherwise FileNotFoundError."""
    folder = courses / valid_name(name, "The course")
    if not folder.is_dir():
        raise FileNotFoundError(f"No course “{name}”.")
    return folder


def new_course_dir(courses: Path, name: str) -> Path:
    """Where a course with this name goes, one that does not exist yet; if it does, ValueError."""
    folder = courses / valid_name(name, "The course")
    if folder.exists():
        raise ValueError(f"A course “{name}” already exists.")
    return folder


@contextmanager
def atomic(path: Path) -> Iterator[Path]:
    """Where to write `path` so that it arrives whole or not at all: a separate file (or
    folder) next to it, which takes its place once the block is done and disappears if the
    block is interrupted. Before taking its place it goes truly to disk, not just to the
    cache: after a blackout a file is there whole or not there, never empty. The extension
    stays last (audio.partial.wav): ffmpeg looks at it."""
    partial = path.with_name(f"{path.stem}.partial{path.suffix}")
    _remove(partial)                       # the leftovers of an attempt interrupted by a restart
    try:
        yield partial
        if partial.is_dir():               # the frames: a flat folder of files
            for file in partial.iterdir():
                _fsync(file)
        _fsync(partial)
        partial.replace(path)
        _fsync(path.parent)
    finally:
        _remove(partial)


def write_json(path: Path, data) -> None:
    """A JSON file of the lecture, whole or not at all (atomic)."""
    with atomic(path) as partial:
        partial.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def read_json(path: Path):
    """A JSON file of the lecture, as write_json wrote it."""
    return json.loads(path.read_text(encoding="utf-8"))


def _fsync(path: Path) -> None:
    """A file on disk, or a folder's listing: fsync of that one path, never a sync of the
    whole machine, which would also wait for network drives."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def move_to_trash(path: Path, courses: Path) -> None:
    """A course or a lecture into the trash, as it was: courses/.trash/<now>/<its path>.
    It is a move on the same disk, instant."""
    target = courses / TRASH / datetime.now().strftime(TRASH_DATE_FORMAT) / path.relative_to(courses)
    target.parent.mkdir(parents=True, exist_ok=True)
    path.rename(target)


def empty_trash(courses: Path, now: datetime) -> None:
    """Out of the trash with whatever went in more than TRASH_DAYS days ago. The date is in
    the name, the date of the deletion: the files' dates stay those of the lecture, and would
    lie. A name that is not a date does not belong to the trash: it stays. An entry that
    cannot be removed (a permission changed by hand) is reported in the logs and stays: the
    trash must not stop the app from starting."""
    trash = courses / TRASH
    if not trash.is_dir():
        return
    for entry in trash.iterdir():
        try:
            when = datetime.strptime(entry.name, TRASH_DATE_FORMAT)
        except ValueError:
            continue
        if now - when > timedelta(days=TRASH_DAYS):
            try:
                shutil.rmtree(entry)
            except OSError as error:
                print(f"trash: cannot remove {entry}: {error}", file=sys.stderr, flush=True)


@dataclass(frozen=True)
class Lecture:
    root: Path
    course: str
    format: str       # VIDEO or AUDIO: the extension of the lecture's file

    @classmethod
    def for_media(cls, courses: Path, course: str, file: Path) -> Lecture:
        """courses/<course>/<file name>/: the names become folders, as they are."""
        suffix = file.suffix.lower()
        if suffix not in FORMATS:
            raise ValueError(f"“{file.name}”: a lecture is a {VIDEO} video or an {AUDIO} audio.")
        return cls(courses / valid_name(course, "The course") / valid_name(file.stem, "The file name"),
                   course, suffix)

    @classmethod
    def find(cls, courses: Path, course: str, name: str) -> Lecture:
        """A lecture of the course, by name; if it is not there, FileNotFoundError."""
        for lecture in cls.of_course(courses, course):
            if lecture.name == name:
                return lecture
        raise FileNotFoundError(f"No lecture “{name}” in {course}.")

    @classmethod
    def of_course(cls, courses: Path, course: str) -> list[Lecture]:
        """The lectures of a course that exists, finished or half-done (those with their file), by name."""
        result = []
        for d in sorted(course_dir(courses, course).iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                result += [c for c in (cls(d, course, f) for f in FORMATS) if c.media.is_file()][:1]
        return result

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def finished(self) -> bool:
        return self.page.exists()

    @property
    def audio_only(self) -> bool:
        return self.format == AUDIO

    @property
    def key(self) -> str:
        """The lecture's name among all of them: course/lecture (the ticks in the browser live under it)."""
        return f"{self.course}/{self.name}"

    @property
    def page(self) -> Path:
        return self.root / LECTURE_PAGE

    @property
    def course_index(self) -> Path:
        return self.root.parent / INDEX

    @property
    def home_index(self) -> Path:
        return self.courses / INDEX

    @property
    def courses(self) -> Path:
        return self.root.parent.parent

    @property
    def media(self) -> Path:
        """The lecture's file: the video, or the audio."""
        return self.root / f"{self.name}{self.format}"

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def language_file(self) -> Path:
        return self.work / "language.txt"

    @property
    def language(self) -> str:
        """The language the lecturer speaks (a key of LANGUAGES), chosen at upload."""
        return self.language_file.read_text(encoding="utf-8").strip()

    @property
    def slides(self) -> Path:
        return self.work / "slides"

    @property
    def audio(self) -> Path:
        return self.work / "audio.wav"

    @property
    def frames(self) -> Path:
        return self.work / "frames"

    @property
    def screens(self) -> Path:
        return self.work / "screens"

    @property
    def previews(self) -> Path:
        return self.work / "previews"

    @property
    def transcript(self) -> Path:
        return self.work / "transcript.json"

    @property
    def alignment(self) -> Path:
        return self.work / "alignment.json"

    @property
    def report(self) -> Path:
        return self.work / "report.json"

    @property
    def check(self) -> Path:
        return self.work / "check.html"

    def to_back_up(self) -> list[Path]:
        """What of the lecture does not rebuild itself, among the files that are there: the
        lecture's file, its language, the slides, the transcript, the alignment, the report and
        the page.
        The rest of work/ is rebuilt from the lecture's file (check.html included, which is
        no use without the frames)."""
        return [f for f in (self.media, self.language_file, *self.pdfs(), self.transcript, self.alignment,
                            self.report, self.page) if f.is_file()]

    def pdfs(self) -> list[Path]:
        """The lecture's slides, by name."""
        return sorted(self.slides.glob(f"*{PDF}"))

    def screen(self, second: int) -> Path:
        """Where the video's full frame at a given second lives (video.screen extracts it)."""
        return self.screens / f"{second:05d}.png"
