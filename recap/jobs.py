"""The app's jobs. Every lecture uploaded from the browser becomes a Job: it waits in the queue
and is processed when its turn comes, one at a time (transcription takes the CPU's fast
cores and almost 3 GB of memory: two at once would not finish sooner). The Job runs the lecture
in a process of its own (python -m recap.processing) and reads its progress, step by step: the
app shows it.

One process per lecture means STOPPING is immediate at any step: the process dies with
everything it started (ffmpeg, claude). And Whisper's memory is freed after every lecture; if
memory runs out, only the lecture's process dies, and the app stays up.

DELETING a lecture, finished or not, or a whole course, stops it and moves it to the trash
(storage.move_to_trash), where it disappears after 30 days. A course can be RENAMED when all
its lectures are done (none queued, running or stopped by an error): the folder takes the new
name and the lecture pages, which carry it, are rebuilt from their files; if one fails,
everything goes back to the old name. An upload in progress to a course that is meanwhile
renamed or deleted does not arrive: it has to be redone. A done lecture's TITLE can be changed,
the one the model wrote in the report: the page is rebuilt, and if that fails the report goes back
to what it was. The lecture's file name stays the uploaded one. A blackout right while the
pages are being rebuilt can leave some with the old title or name: making the change again
fixes it (the title can be sent again even unchanged).

Live state lives in memory; what survives a restart or a blackout is the disk. At startup
every half-done lecture (with its file and no page) goes back in the queue on its own, and
resumes where it was.

UPLOADS arrive in courses/.incoming/<id>/, one file per request. Where the lecture will go is
checked when the upload opens, before a single byte is sent, and again at delivery: meanwhile
another tab may have taken the name. When the browser delivers
them, the lecture file and the PDFs move into the new lecture's folder (moved, not copied:
same disk) and the lecture joins the queue. A half-received file disappears at once, a
delivered or cancelled upload disappears whatever happens; only one abandoned between one file
and the next (the browser closed) waits for the next startup.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import uuid
from pathlib import Path
from typing import BinaryIO

from . import page
from .storage import (FORMATS, INCOMING, LANGUAGES, PDF, Lecture, atomic, course_dir, list_courses,
                      move_to_trash, new_course_dir, read_json, valid_name, write_json)

# A lecture's steps (processing.process), in order: (id, name shown to the user, weight).
# The weight is the seconds the step took on the 82-minute test lecture (transcription on an
# i5-12600H, the others on a Ryzen 5 3600): the overall bar moves with real time.
STEPS = (
    ("audio", "Audio for transcription", 10),
    ("frames", "One frame per second", 60),
    ("transcription", "Speech transcription", 1355),
    ("alignment", "Slides, screens and speech aligned", 35),
    ("report", "Notes", 660),
    ("page", "Lecture page", 3),
    ("indexes", "Course indexes", 1),
)
MAX_FILE_SIZE = 8 * 1024 ** 3  # bytes per uploaded file: a three-hour lecture fits easily
CHUNK = 1024 * 1024
ACTIVE_STATES = ("queued", "running")
MAX_TITLE = 200                # characters in a lecture's title


def valid_title(title: str) -> str:
    """A lecture's title as the user wrote it, on one line: every space (including the
    non-breaking space of pasted text) and every line break become a single space. From 1 to
    MAX_TITLE characters, no control characters; otherwise ValueError."""
    title = " ".join(title.split())
    if not 0 < len(title) <= MAX_TITLE:
        raise ValueError(f"The title must be 1 to {MAX_TITLE} characters long.")
    if any(unicodedata.category(c) in ("Cc", "Cs") for c in title):
        raise ValueError("The title contains control characters.")
    return title


def copy_stream(src: BinaryIO, dst: BinaryIO, count: int) -> int:
    """Up to `count` bytes from one stream to the other, in chunks; returns how many went
    across (fewer, if `src` ends first)."""
    copied = 0
    while copied < count:
        chunk = src.read(min(CHUNK, count - copied))
        if not chunk:
            break
        dst.write(chunk)
        copied += len(chunk)
    return copied


class Job:
    """A lecture queued or being processed, and how far along it is: queued → running → done,
    or error."""

    def __init__(self, lecture: Lecture):
        self.id = uuid.uuid4().hex[:12]
        self.lecture = lecture
        self._state = "queued"
        self._error = ""
        self._steps = {step: {"state": "waiting", "fraction": 0.0, "start": None, "end": None, "note": ""}
                       for step, _, _ in STEPS}
        self._process: subprocess.Popen | None = None
        self._stopped = False
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._state in ACTIVE_STATES

    @property
    def current(self) -> bool:
        """Whether it still says how the lecture is: "done" holds as long as the page exists (a
        lecture can also be removed from the disk by hand)."""
        return self._state != "done" or self.lecture.finished

    # The Progress events, as they arrive from the lecture's process.
    def start(self, step: str) -> None:
        with self._lock:
            self._steps[step].update(state="running", start=time.monotonic())

    def progress(self, step: str, fraction: float) -> None:
        with self._lock:
            self._steps[step]["fraction"] = fraction

    def finish(self, step: str, note: str = "") -> None:
        with self._lock:
            self._steps[step].update(state="done", fraction=1.0, end=time.monotonic(), note=note)

    def run(self) -> None:
        """Processes the lecture in its own process, following its events; whatever goes wrong
        becomes the job's error, and the worker moves on to the next one. A job stopped while
        it was waiting does not start."""
        with self._lock:
            if self._stopped:
                return
            try:
                self._process = subprocess.Popen(
                    [sys.executable, "-m", "recap.processing", str(self.lecture.courses), self.lecture.course,
                     self.lecture.name],
                    stdout=subprocess.PIPE, text=True, encoding="utf-8", start_new_session=True)
            except OSError as e:
                self._fail(f"the lecture's process did not start: {e}")
                return
            self._state = "running"
        try:
            error = self._follow()
        except Exception as e:                  # an unreadable channel: the process is of no use any more
            traceback.print_exc()
            self._kill()
            error = f"unreadable progress: {e}"
        code = self._process.wait()
        with self._lock:
            if self._stopped:                   # the queue has already dropped it: nobody looks at it any more
                return
            if code == 0 and not error:
                self._state = "done"
            else:
                self._fail(error or ("the lecture's process was killed: out of memory?"
                                     if code == -signal.SIGKILL
                                     else f"the lecture's process exited with {code}"))

    def _follow(self) -> str:
        """Applies the process's events, line by line; returns its error message, if it sends
        one."""
        error = ""
        for line in self._process.stdout:
            event, *args = json.loads(line)
            if event == "error":
                error = args[0]
            else:
                {"start": self.start, "progress": self.progress, "finish": self.finish}[event](*args)
        return error

    def _fail(self, message: str) -> None:
        """The job stops in error, on the step it was at (with the lock held)."""
        for s in self._steps.values():
            if s["state"] == "running":
                s.update(state="error", end=time.monotonic())
        self._state, self._error = "error", message

    def stop(self) -> None:
        """Queued, it will not start; running, its process dies, with everything it started
        (ffmpeg, claude). Returns when nothing is running any more."""
        with self._lock:
            self._stopped = True
            process = self._process
        if process is not None:
            self._kill()
            process.wait()

    def _kill(self) -> None:
        """The lecture's process and its group: ffmpeg and claude belong to it."""
        try:
            os.killpg(self._process.pid, signal.SIGKILL)
        except ProcessLookupError:              # it had just finished on its own
            pass

    def snapshot(self) -> dict:
        """The state for the browser: every step with how far it got and how long it has taken,
        and the overall fraction, with the steps weighted by the time they usually take."""
        with self._lock:
            now, steps, done = time.monotonic(), [], 0.0
            for step, name, weight in STEPS:
                s = self._steps[step]
                seconds = None if s["start"] is None else round((s["end"] or now) - s["start"])
                steps.append({"id": step, "name": name, "state": s["state"], "fraction": round(s["fraction"], 3),
                              "seconds": seconds, "note": s["note"]})
                done += weight * s["fraction"]
            return {"id": self.id, "lecture": self.lecture.name, "state": self._state, "active": self.active,
                    "error": self._error,
                    "fraction": round(done / sum(weight for _, _, weight in STEPS), 3), "steps": steps,
                    "page": page.link(self.lecture.course_index.parent, self.lecture.page)}


class JobQueue:
    """The line of jobs, with the single worker that processes them one after the other. Every
    operation on lectures and courses (enqueueing, resuming, deleting, renaming, changing a
    title) happens under the same lock, from the check to the last write: two requests at once
    do not trip over each other."""

    def __init__(self, courses: Path):
        self.courses = courses
        self._jobs: dict[Lecture, Job] = {}     # one per lecture, the latest: resuming it replaces it
        self._line: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._work, name="worker", daemon=True).start()

    def requeue_interrupted(self) -> None:
        """At startup: every half-done lecture goes back in the queue, and resumes where it was."""
        with self._lock:
            for name in list_courses(self.courses):
                for lecture in Lecture.of_course(self.courses, name):
                    if not lecture.finished:
                        self._enqueue(lecture)

    def enqueue(self, lecture: Lecture) -> None:
        """A lecture with its file and slides already in its folder joins the line."""
        with self._lock:
            self._enqueue(lecture)

    def resume(self, course: str, name: str) -> None:
        """Puts a lecture stopped by an error back in the queue, with the file and slides it
        already has: the steps already done are skipped."""
        with self._lock:
            lecture = Lecture.find(self.courses, course, name)
            if lecture.finished:
                raise ValueError(f"“{name}” is already finished.")
            self._enqueue(lecture)

    def delete(self, course: str, name: str) -> None:
        """Removes a lecture, finished or not: stops its job, if there is one, and moves it to
        the trash with its file, its slides and whatever had been done."""
        with self._lock:
            lecture = Lecture.find(self.courses, course, name)
            self._stop(lecture)
            move_to_trash(lecture.root, self.courses)

    def delete_course(self, course: str) -> None:
        """Removes a whole course: stops its lectures' jobs and moves it to the trash."""
        with self._lock:
            folder = course_dir(self.courses, course)
            for lecture in [lec for lec in self._jobs if lec.course == course]:
                self._stop(lecture)
            move_to_trash(folder, self.courses)

    def set_title(self, course: str, name: str, title: str) -> None:
        """The title of a finished lecture, the bold one the model gave it: it changes in the
        report, and the page is rebuilt. If the page fails, the report goes back to what it was
        (the old page is intact: it is written whole or not at all). If instead the app shuts
        down right while rebuilding it, report and page are left with two different titles, and
        startup does not realign them: that is why the title can be sent again unchanged, and
        the page is rebuilt all the same."""
        title = valid_title(title)
        with self._lock:
            lecture = Lecture.find(self.courses, course, name)
            if not lecture.finished:
                raise ValueError(f"“{name}” is not finished: its title can be changed once it is done.")
            report = read_json(lecture.report)
            write_json(lecture.report, {**report, "title": title})
            try:
                page.write(lecture)
            except Exception:
                write_json(lecture.report, report)
                raise

    def rename_course(self, course: str, new_name: str) -> None:
        """A course with its new name, and its lectures' pages rebuilt: they carry the course's
        name. Only if all its lectures are finished. If a page fails, the folder goes back to
        the old name, and with it the pages already rebuilt."""
        with self._lock:
            folder = course_dir(self.courses, course)
            lectures = Lecture.of_course(self.courses, course)
            if not all(lec.finished for lec in lectures):
                raise ValueError(f"“{course}” has unfinished lectures (being processed or stopped by an error): "
                                 "it can be renamed once they are done or deleted.")
            new_folder = new_course_dir(self.courses, new_name)
            folder.rename(new_folder)
            rebuilt = 0
            try:
                for lecture in lectures:
                    page.write(Lecture(new_folder / lecture.name, new_name, lecture.format))
                    rebuilt += 1
            except Exception:
                new_folder.rename(folder)
                for lecture in lectures[:rebuilt]:
                    page.write(lecture)
                raise
            for lecture in [lec for lec in self._jobs if lec.course == course]:
                del self._jobs[lecture]

    def of_course(self, course: str) -> list[Job]:
        """The course's jobs that still tell the truth (Job.current)."""
        with self._lock:
            return [job for job in self._jobs.values() if job.lecture.course == course and job.current]

    def _enqueue(self, lecture: Lecture) -> None:
        old = self._jobs.get(lecture)
        if old is not None and old.active:
            raise ValueError(f"“{lecture.name}” is already being processed.")
        job = Job(lecture)
        self._jobs[lecture] = job
        self._line.put(job)

    def _stop(self, lecture: Lecture) -> None:
        job = self._jobs.pop(lecture, None)
        if job is not None:
            job.stop()

    def _work(self) -> None:
        while True:
            self._line.get().run()


class Uploads:
    """The browser's uploads: first the files, one per request, then the delivery that turns
    them into a lecture."""

    def __init__(self, courses: Path):
        self.courses = courses
        self.root = courses / INCOMING
        shutil.rmtree(self.root, ignore_errors=True)      # the ones never delivered: the app had shut down

    def open(self, course: str, file: str, slides: list[str], language: str) -> str:
        """A new upload, once the lecture it will become can go where it is headed."""
        self._target(course, file, slides, language)
        id = uuid.uuid4().hex
        (self.root / id).mkdir(parents=True)
        return id

    def receive(self, id: str, name: str, stream: BinaryIO, length: int) -> None:
        """One file of the upload, read from the request's stream: whole or nothing."""
        upload = self._upload(id)
        name = valid_name(name, "The file")
        if Path(name).suffix.lower() not in (*FORMATS, PDF):
            raise ValueError(f"“{name}”: only the lecture ({', '.join(FORMATS)}) and the slides ({PDF}) "
                             "can be uploaded.")
        if not 0 < length <= MAX_FILE_SIZE:
            raise ValueError(f"“{name}”: size not accepted ({length} bytes).")
        with atomic(upload / name) as partial, partial.open("wb") as file:
            if copy_stream(stream, file, length) < length:
                raise ValueError(f"“{name}”: upload interrupted.")

    def deliver(self, id: str, course: str, file: str, slides: list[str], language: str) -> Lecture:
        """The lecture file and the slides into the new lecture's folder, with its language,
        ready for the queue, with lowercase extensions. A lecture with the same name is not
        overwritten. After this the upload is no longer needed: to retry, the browser opens a
        new one."""
        upload = self._upload(id)
        try:
            lecture = self._target(course, file, slides, language)
            missing = [n for n in (file, *slides) if not (upload / valid_name(n, "The file")).is_file()]
            if missing:
                raise ValueError(f"Not received: {', '.join(missing)}.")
            lecture.slides.mkdir(parents=True)
            with atomic(lecture.language_file) as partial:
                partial.write_text(language, encoding="utf-8")
            (upload / file).replace(lecture.media)
            for name in slides:
                (upload / name).replace(lecture.slides / f"{Path(name).stem}{PDF}")
            return lecture
        finally:
            shutil.rmtree(upload)

    def _target(self, course: str, file: str, slides: list[str], language: str) -> Lecture:
        """Where the upload goes: a lecture that does not exist yet, in a course that does, with
        its slides and a known language; otherwise ValueError or FileNotFoundError."""
        if language not in LANGUAGES:
            raise ValueError(f"The lecture's language must be one of: {', '.join(LANGUAGES.values())}.")
        course_dir(self.courses, course)
        lecture = Lecture.for_media(self.courses, course, Path(valid_name(file, "The file")))
        if not slides or any(Path(s).suffix.lower() != PDF for s in slides):
            raise ValueError(f"The slides ({PDF}) are required.")
        if len({Path(valid_name(s, "The file")).stem.lower() for s in slides}) < len(slides):
            raise ValueError("Two PDFs have the same name.")
        if lecture.root.exists():
            state = "finished" if lecture.finished else "being processed"
            raise ValueError(f"{course} already has a lecture “{lecture.name}” ({state}).")
        return lecture

    def cancel(self, id: str) -> None:
        """An upload the browser left half-done: away with the files already received. It is
        first moved out of the place the PUTs write to, then deleted: a PUT still in flight can
        no longer add anything to it."""
        cancelled = self._upload(id).rename(self.root / f"{id}.cancelled")
        shutil.rmtree(cancelled)

    def _upload(self, id: str) -> Path:
        upload = self.root / id
        if not re.fullmatch(r"[0-9a-f]{32}", id) or not upload.is_dir():
            raise FileNotFoundError("Unknown upload: start again.")
        return upload
