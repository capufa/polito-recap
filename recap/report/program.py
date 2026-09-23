"""The vendors' own programs, for the providers that sign in with a subscription: Claude Code
(claude.py), Codex (codex.py) and Antigravity CLI (antigravity.py).

They are not in the image. The setup installs the one chosen, from its vendor, into its own
home in the accounts volume (/accounts/<name>, docker-compose.yml), where the program also
keeps its own sign-in: this app never reads, stores or passes a subscription's token, and the
sign-in happens in the vendor's own flow. Two reasons: the licences (a published image would
redistribute programs that are not ours to redistribute), and the vendors retire models within
weeks, so their programs must be updatable without a release of this app — running the setup
again installs them afresh (a pinned version for Claude Code, see claude.py).

Every run gets a clean environment — the program's home and PATH, its own settings, whatever
the caller adds (an API key) and nothing else: no other provider's key reaches it — in an empty
folder of its own, since a program started in a folder reads the settings and hooks it finds
there. The app never lets a program update itself: what ran yesterday runs today.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ACCOUNTS = Path("/accounts")              # the volume, docker-compose.yml
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
# All a program gets from the app's own environment: language, time zone, and the terminal's
# kind, without which a sign-in's full-screen interface cannot draw itself.
PASSED = ("LANG", "LC_ALL", "TZ", "TERM", "COLORTERM")


@dataclass(frozen=True)
class Program:
    name: str                             # its folder in the volume
    title: str                            # for people
    binary: str                           # the executable, from its home
    credentials: str                      # the file of its sign-in, from its home
    installer: str                        # the vendor's install script
    shell: str = "bash"                   # what runs the install script
    version: str = ""                     # pinned; empty: the vendor's latest
    sign_in_args: tuple[str, ...] = ()    # the vendor's own sign-in; empty: the program itself
    environment: dict = field(default_factory=dict)      # for every run: no self-update, no telemetry…
    install_environment: dict = field(default_factory=dict)

    @property
    def home(self) -> Path:
        return ACCOUNTS / self.name

    @property
    def path(self) -> Path:
        return self.home / self.binary

    def signed_in(self) -> bool:
        return (self.home / self.credentials).is_file()

    def check(self, signed_in: bool = True) -> None:
        """At startup: installed, signed in (unless an API key pays), and its home writable,
        since the sign-in renews itself there."""
        if not self.path.exists():
            raise ValueError(f"{self.title} is not installed yet")
        if signed_in and not self.signed_in():
            raise ValueError(f"{self.title} is not signed in")
        if not os.access(self.home, os.W_OK):
            raise PermissionError(f"the app's user {os.getuid()}:{os.getgid()} cannot write to {self.title}'s "
                                  f"folder in the accounts volume")

    def run(self, args: list[str], *, input: str | None = None, cwd: Path | None = None,
            timeout: float | None = None, extra: dict | None = None,
            interactive: bool = False) -> subprocess.CompletedProcess:
        """The program with these arguments, in `cwd` or in an empty folder of its own. Output
        captured as text, unless interactive: then it talks to the terminal (the setup's
        sign-in)."""
        with tempfile.TemporaryDirectory() as empty:
            return subprocess.run([str(self.path), *args], input=input, cwd=cwd or empty, timeout=timeout,
                                  env=self._environment(extra), text=True, encoding="utf-8",
                                  capture_output=not interactive)

    def install(self) -> None:
        """The vendor's install script, fetched with curl as the vendors say (their sites turn
        other clients away) and run with this program's home: the setup, as root. Its output
        goes to the terminal; a failure is a RuntimeError that says where."""
        if self.version and self.path.exists() and self.version in self.run(["--version"], timeout=60).stdout:
            return
        self.home.mkdir(parents=True, exist_ok=True)
        self.path.unlink(missing_ok=True)       # some installers do nothing if the program is there
        script = subprocess.run(["curl", "-fsSL", self.installer], capture_output=True, text=True, timeout=120)
        if script.returncode != 0:
            raise RuntimeError(f"cannot download {self.installer}: {script.stderr.strip()}")
        downloads = self.home / ".install"      # on the volume: the setup's own /tmp is small
        downloads.mkdir(exist_ok=True)
        # Run by root, tar keeps an archive's owners, and then may not set the files' modes: the
        # setup lacks that capability. The files are root's until give() hands them over anyway.
        done = subprocess.run([self.shell, "-s", *([self.version] if self.version else [])], input=script.stdout,
                              text=True, cwd=self.home,
                              env=self._environment({"TMPDIR": str(downloads), "TAR_OPTIONS": "--no-same-owner",
                                                     **self.install_environment}))
        shutil.rmtree(downloads)
        if done.returncode != 0 or not self.path.exists():
            raise RuntimeError(f"{self.title}'s installer failed (exit {done.returncode})")

    def give(self, owner: tuple[int, int]) -> None:
        """Everything in its home to the app's user, the home closed to anyone else: it holds a
        sign-in. Links are changed themselves, never followed. The mode first, and only if it
        differs: once the home is the user's, the setup may no longer change it."""
        if stat.S_IMODE(self.home.stat().st_mode) != 0o700:
            os.chmod(self.home, 0o700)
        for root, folders, files in os.walk(self.home):
            for name in folders + files:
                os.chown(os.path.join(root, name), *owner, follow_symlinks=False)
        os.chown(self.home, *owner)

    def _environment(self, extra: dict | None) -> dict:
        environment = {name: os.environ[name] for name in PASSED if name in os.environ}
        environment.update(HOME=str(self.home), PATH=f"{self.home / '.local/bin'}:{SYSTEM_PATH}")
        return {**environment, **self.environment, **(extra or {})}
