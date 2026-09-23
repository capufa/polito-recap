"""The backup copy into another folder, usually a NAS: every hour, whatever of each finished
lecture cannot be rebuilt on its own (Lecture.to_back_up) goes from courses/ to the copy.
The extracts in work/ and the indexes are rebuilt, and stay out; a half-done lecture waits
until it is finished, so a cancelled lecture leaves nothing in the copy.

It is a copy, not a mirror: a new or changed file is copied, nothing is deleted, and a
lecture removed from courses/ (or moved to the trash) stays on the NAS. If a lecture is
deleted and another one is uploaded with the same name, the old one on the NAS is moved
aside, with its name and the date: the two never mix. It runs in a separate container
(docker-compose.yml) that sees courses/ read-only: it cannot touch the lectures.

THE NAS CAN BE MISSING: after a blackout it boots slower than the computer. The container
does not depend on it to start, and each pass begins by checking that its folder is there:
if the NAS is not mounted it is not, and the pass is put off, without creating anything on
the computer's disk. If the NAS goes off mid-pass, a "hard" NFS mount holds it until it
comes back.

    python -m recap.backup --courses DIR --dest DIR
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from .storage import FORMATS, TRASH_DATE_FORMAT, Lecture, atomic, list_courses

EVERY = 3600       # seconds between one pass and the next


def copy(courses: Path, dest: Path) -> list[Path]:
    """One pass: copies the new or changed files, each whole or not at all, and returns them.
    The backup folder must already be there: it is never created here."""
    if not dest.is_dir():
        raise FileNotFoundError(f"{dest} is not there: is the NAS not mounted?")
    copied = []
    for course in list_courses(courses):
        for lecture in (c for c in Lecture.of_course(courses, course) if c.finished):
            _make_room(lecture, dest / lecture.root.relative_to(courses))
            for file in lecture.to_back_up():
                target = dest / file.relative_to(courses)
                if _same(file, target):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with atomic(target) as partial:
                    shutil.copy2(file, partial)
                copied.append(file)
    return copied


def _make_room(lecture: Lecture, on_nas: Path) -> None:
    """If on the NAS, in the lecture's place, there is another lecture with the same name
    (its file differs), that one is moved aside, with its name and the current date."""
    for fmt in FORMATS:
        file = on_nas / f"{lecture.name}{fmt}"
        if file.is_file() and not _same(lecture.media, file):
            on_nas.rename(on_nas.with_name(f"{on_nas.name} {datetime.now().strftime(TRASH_DATE_FORMAT)}"))
            return


def _same(original: Path, copied: Path) -> bool:
    """Same size and same date (copy2 carries it over): the file is already copied."""
    if not copied.is_file():
        return False
    a, b = original.stat(), copied.stat()
    return a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime)


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m recap.backup", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--courses", type=Path, required=True, help="the lectures to copy")
    p.add_argument("--dest", type=Path, required=True, help="where to copy them, on the NAS")
    a = p.parse_args()
    while True:
        try:
            copied = copy(a.courses, a.dest)
        # The NAS not there yet, or an error on the NAS (permissions, space, stale handle): try
        # again at the next pass.
        except OSError as error:
            print(f"backup failed: {error}", file=sys.stderr, flush=True)
        else:
            if copied:
                print(f"copied {len(copied)} files: " + ", ".join(str(f.relative_to(a.courses)) for f in copied),
                      flush=True)
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
