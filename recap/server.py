"""The app: the web server that serves the pages in courses/, creates new courses, hands new
lectures to the job queue (jobs.py), renames courses, changes lecture titles and deletes
both. It runs in the container (docker-compose.yml).

    GET  /                                      → the home, /courses/index.html
    GET  /courses/…                             pages, images, videos and audio
                                                (with Range: the video can jump back and forth)
    POST /api/courses                  {name}   a new course
    POST /api/uploads  {course, lecture, slides, language}   opens an upload, once its lecture can go there: {id}
    PUT  /api/uploads/<id>/<file>               one file of the upload: the body is the file
    DELETE /api/uploads/<id>                    a cancelled upload: away with the received files
    POST /api/lectures  {course, upload, lecture, slides, language}   the lecture joins the queue
    GET  /api/courses/<course>/jobs             the course's jobs
    POST /api/courses/<course>/lectures/<lecture>/resume   a lecture stopped by an error
    DELETE /api/courses/<course>/lectures/<lecture>   the lecture to the trash (stops its job)
    DELETE /api/courses/<course>                the course to the trash, with its lectures
    POST /api/courses/<course>/lectures/<lecture>/title  {title}   a finished lecture, new title
    POST /api/courses/<course>/rename           {name}   a course, new name
    GET  /api/version                           this version, and whether there is a newer one (updates.py)

At startup the half-done lectures go back in the queue on their own (a restart or a blackout
does not lose them) and the indexes are rebuilt; every day the trash drops what has expired.
If the address to listen on is not there yet (after a blackout the router, with its DHCP, can
come back after this computer), the app waits for it.

First, though, it checks what it can without the network: the settings, and the data folders
it must write to. If one is wrong or missing — no key yet, on the first start — the app
starts nothing else, and every request gets a page that says what and how to fix it: the
setup (setup.py). The page holds nothing a stranger could use: no key, no data.

SECURITY. No login: whoever reaches the app can do everything. That is why by default it
listens only on this computer (docker-compose.yml); opening it to the home network is a choice
(README), to the internet never. It answers only if the Host is an IP address, localhost or one
of the names in RECAP_HOSTNAMES: any other name is what a site open in the browser would use to
get here (DNS rebinding). Every API request needs the X-Recap header: an arbitrary site cannot
send it without a CORS permission, which is not granted here. Nor can a site frame the app and
trick a click (clickjacking): served files carry frame-ancestors 'none'. Course and file names
go through storage.valid_name; served files must be inside courses/, outside the hidden folders.
"""
from __future__ import annotations

import errno
import html
import ipaddress
import json
import os
import re
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from . import report
from .jobs import JobQueue, Uploads, copy_stream
from .page import document, indexes
from .settings import load, version
from .storage import FORBIDDEN, INDEX, course_dir, empty_trash, new_course_dir
from .updates import Updates

MAX_JSON = 64 * 1024
NETWORK_WAIT = 5         # seconds between attempts to open the port, after a blackout
ONE_DAY = 24 * 3600
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json", ".mp4": "video/mp4",
                 ".mp3": "audio/mpeg", ".png": "image/png", ".pdf": "application/pdf"}


class _HttpError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


class _Listener(ThreadingHTTPServer):
    """A server on host:port, which waits for the address if this computer does not have it yet."""
    daemon_threads = True

    def __init__(self, address: str, handler: type[BaseHTTPRequestHandler]):
        host, port = address.rsplit(":", 1)
        while True:
            try:
                super().__init__((host, int(port)), handler)
                return
            except OSError as error:
                if error.errno != errno.EADDRNOTAVAIL:
                    raise
                print(f"waiting for this computer to have the address {host}…", flush=True)
                time.sleep(NETWORK_WAIT)


class _NotReady(_Listener):
    """The app when something keeps it from working: one page, whatever the request."""

    def __init__(self, address: str, problem: str):
        super().__init__(address, _NotReadyHandler)
        body = ('<main class="sheet"><h1>PoliTo Recap is not set up</h1>'
                f'<p class="caveat">{html.escape(problem)}.</p>'
                '<p>In the folder with <code>docker-compose.yml</code>, run the setup, then start the app '
                'again:</p><p><code>docker compose run --rm setup</code><br><code>docker compose up -d</code></p>'
                '<p class="meta">README, “Install”.</p></main>')
        self.page = document("PoliTo Recap", body, scripts=()).encode("utf-8")


class _NotReadyHandler(BaseHTTPRequestHandler):
    server: _NotReady

    def do_GET(self) -> None:
        self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
        self.send_header("Content-Type", CONTENT_TYPES[".html"])
        self.send_header("Content-Length", str(len(self.server.page)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(self.server.page)

    do_POST = do_PUT = do_DELETE = do_GET


class _Server(_Listener):
    def __init__(self, courses: Path, address: str):
        super().__init__(address, _Handler)
        self.courses = courses
        self.jobs = JobQueue(courses)
        self.uploads = Uploads(courses)
        self.hostnames = load().hostnames
        self.updates = Updates(load().update_url, version())


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    timeout = 60        # seconds of silence on a connection: then the thread is freed

    def do_GET(self) -> None:
        self._respond("GET")

    def do_POST(self) -> None:
        self._respond("POST")

    def do_PUT(self) -> None:
        self._respond("PUT")

    def do_DELETE(self) -> None:
        self._respond("DELETE")

    def log_request(self, code="-", size="-") -> None:
        if isinstance(code, int) and code >= 400:       # the rest is noise: the page polls every second
            super().log_request(code, size)

    def _respond(self, method: str) -> None:
        try:
            if not _host_allowed(self.headers.get("Host", ""), self.server.hostnames):
                raise _HttpError(HTTPStatus.FORBIDDEN,
                                 "Unknown Host: if you reach the app by a name, add it to RECAP_HOSTNAMES.")
            parts = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
            if parts[:1] == ["api"]:
                if self.headers.get("X-Recap") != "1":
                    raise _HttpError(HTTPStatus.FORBIDDEN, "The X-Recap header is missing.")
                self._json(HTTPStatus.OK, self._api(method, parts[1:]))
            elif method != "GET":
                raise _HttpError(HTTPStatus.METHOD_NOT_ALLOWED, "Read only.")
            elif not parts:
                self._redirect(f"/courses/{INDEX}")
            elif parts == ["favicon.ico"]:
                self._no_content()                       # the app has no icon: the browser asks for it anyway
            elif parts[0] == "courses":
                self._file(parts[1:])
            else:
                raise _HttpError(HTTPStatus.NOT_FOUND, "No such page.")
        except _HttpError as e:
            self._json(e.status, {"error": str(e)})
        except ValueError as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        except FileNotFoundError as e:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass                                         # the browser closed or went silent: seeking in the video
        except Exception as e:
            self.log_error("%s", repr(e))
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"internal error: {e}"})

    def _api(self, method: str, parts: list[str]) -> dict:
        courses, jobs, uploads = self.server.courses, self.server.jobs, self.server.uploads
        if method == "GET" and parts == ["version"]:
            return self.server.updates.status()
        if method == "POST" and parts == ["courses"]:
            return _new_course(courses, self._field("name"))
        if method == "POST" and parts == ["uploads"]:
            return {"id": uploads.open(*self._lecture_fields(self._body()))}
        if method == "PUT" and len(parts) == 3 and parts[0] == "uploads":
            uploads.receive(parts[1], parts[2], self.rfile, int(self.headers.get("Content-Length") or 0))
            return {}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "uploads":
            uploads.cancel(parts[1])
            return {}
        if method == "POST" and parts == ["lectures"]:
            body = self._body()
            lecture = uploads.deliver(str(body.get("upload", "")), *self._lecture_fields(body))
            jobs.enqueue(lecture)
            return {}
        if len(parts) == 3 and parts[0] == "courses" and parts[2] == "jobs" and method == "GET":
            course_dir(courses, parts[1])
            return {"jobs": [job.snapshot() for job in jobs.of_course(parts[1])]}
        if len(parts) == 5 and parts[0] == "courses" and parts[2] == "lectures" and parts[4] == "resume" \
                and method == "POST":
            jobs.resume(parts[1], parts[3])
            return {}
        if len(parts) == 4 and parts[0] == "courses" and parts[2] == "lectures" and method == "DELETE":
            jobs.delete(parts[1], parts[3])
            indexes.write(courses)
            return {}
        if len(parts) == 2 and parts[0] == "courses" and method == "DELETE":
            jobs.delete_course(parts[1])
            indexes.write(courses)
            return {}
        if len(parts) == 5 and parts[0] == "courses" and parts[2] == "lectures" and parts[4] == "title" \
                and method == "POST":
            try:
                jobs.set_title(parts[1], parts[3], self._field("title"))
            finally:                            # even if not everything went back to how it was
                indexes.write(courses)
            return {}
        if len(parts) == 3 and parts[0] == "courses" and parts[2] == "rename" and method == "POST":
            try:
                jobs.rename_course(parts[1], self._field("name"))
            finally:
                indexes.write(courses)
            return {}
        raise _HttpError(HTTPStatus.NOT_FOUND, "Unknown request.")

    @staticmethod
    def _lecture_fields(body: dict) -> tuple[str, str, list[str], str]:
        """Course, lecture file, slides and language of an upload, as the browser sends them."""
        return (str(body.get("course", "")), str(body.get("lecture", "")), [str(s) for s in body.get("slides", [])],
                str(body.get("language", "")))

    def _field(self, name: str) -> str:
        """A text field of the JSON body, without surrounding whitespace."""
        return str(self._body().get(name, "")).strip()

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_JSON:
            raise ValueError("Empty or too large request.")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Invalid request.")
        return data

    def _json(self, status: HTTPStatus, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _no_content(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _file(self, parts: list[str]) -> None:
        """A file from courses/, whole or in pieces (Range: video and audio jump around in it)."""
        root = self.server.courses
        # Before touching the disk: no separators inside a part, no ".." and no hidden
        # folders.
        if not parts or any(p.startswith(".") or any(c in FORBIDDEN for c in p) for p in parts):
            raise _HttpError(HTTPStatus.NOT_FOUND, "no such file")
        path = root.joinpath(*parts).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise _HttpError(HTTPStatus.NOT_FOUND, "no such file")
        size = path.stat().st_size
        start, end, status = 0, size - 1, HTTPStatus.OK
        requested = self.headers.get("Range")
        if requested:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
            if not m or not (m[1] or m[2]):
                raise _HttpError(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "invalid Range")
            if m[1]:
                start, end = int(m[1]), min(int(m[2]) if m[2] else size - 1, size - 1)
            else:
                start = max(0, size - int(m[2]))
            if start > end:
                raise _HttpError(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "Range outside the file")
            status = HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as file:
            file.seek(start)
            copy_stream(file, self.wfile, end - start + 1)


def _host_allowed(host: str, hostnames: tuple[str, ...]) -> bool:
    """A request's Host: an IP address, localhost or one of the chosen names."""
    try:
        name = urlsplit(f"//{host}").hostname
    except ValueError:
        return False
    if not name:
        return False
    if name == "localhost" or name in hostnames:
        return True
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def _writable(folder: Path) -> None:
    """A data folder: the app must write to it. On Linux one made by Docker belongs to root,
    while the app runs as RECAP_USER: better to say so right away than to fail halfway."""
    if not os.access(folder, os.W_OK):
        raise PermissionError(f"the app runs as user {os.getuid()}:{os.getgid()} (RECAP_USER), which cannot "
                              f"write to its data folder {folder.name}/ (in RECAP_DATA)")


def _new_course(courses: Path, name: str) -> dict:
    new_course_dir(courses, name).mkdir(parents=True)
    indexes.write(courses)
    return {"url": f"/courses/{quote(name)}/{INDEX}"}


def run(courses: Path, address: str) -> None:
    """Starts the app, listening on <address> (host:port); if something keeps it from working,
    only the page that says so."""
    print(f"PoliTo Recap {version()}", flush=True)
    problem = _problem(courses)
    if problem:
        print(f"Not set up: {problem}. Every page says how to fix it.", flush=True)
        _NotReady(address, problem).serve_forever()
        return
    print(load().summary(), flush=True)
    server = _Server(courses.resolve(), address)
    server.updates.start()
    threading.Thread(target=_empty_trash_daily, args=(courses,), name="trash", daemon=True).start()
    server.jobs.requeue_interrupted()
    indexes.write(courses)
    print(f"PoliTo Recap is up: listening on {address}", flush=True)
    server.serve_forever()


def _problem(courses: Path) -> str:
    """What keeps the app from working, as far as it can tell without the network: a wrong or
    missing setting, a data folder it cannot write to. Empty: nothing."""
    try:
        settings = load()
        report.check(settings)
        courses.mkdir(parents=True, exist_ok=True)
        for folder in (courses, settings.models):
            _writable(folder)
    except (ValueError, PermissionError) as problem:
        return str(problem)
    return ""


def _empty_trash_daily(courses: Path) -> None:
    """The trash drops what has expired: at startup, and then once a day."""
    while True:
        empty_trash(courses, datetime.now())
        time.sleep(ONE_DAY)
