"""Whether there is a new version of PoliTo Recap: once a day GitHub is asked for the latest
release (RECAP_UPDATE_URL, GitHub's by default; off: never), and the home page says so, with the link to the
release notes. Updating stays the choice of whoever installed it (README, "Updating"). An
image built from the source, without a version ("dev"), asks nothing."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request

ONE_DAY = 24 * 3600
TIMEOUT = 20         # seconds for GitHub's answer


class Updates:
    def __init__(self, url: str, current: str):
        self._url = url
        self._current = current
        self._latest: dict | None = None        # {"version", "url"} of the latest release
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._url and self._current != "dev":
            threading.Thread(target=self._every_day, name="updates", daemon=True).start()

    def status(self) -> dict:
        with self._lock:
            latest = self._latest
        newer = latest is not None and _numbers(latest["version"]) > _numbers(self._current)
        return {"current": self._current, "latest": latest and latest["version"],
                "newer": newer, "url": latest and latest["url"]}

    def _every_day(self) -> None:
        while True:
            try:
                request = urllib.request.Request(self._url, headers={"Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    release = json.load(response)
                if not release["html_url"].startswith("https://"):
                    raise ValueError(f"odd release notes address: {release['html_url']}")
                with self._lock:
                    self._latest = {"version": release["tag_name"].lstrip("v"), "url": release["html_url"]}
            except (OSError, ValueError, KeyError) as error:       # GitHub not answering: try again tomorrow
                print(f"updates: cannot ask {self._url} for the latest version: {error}",
                      file=sys.stderr, flush=True)
            time.sleep(ONE_DAY)


def _numbers(version: str) -> tuple[int, ...]:
    """'1.10.2' → (1, 10, 2); a version not shaped like that is never newer."""
    parts = version.split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else ()
