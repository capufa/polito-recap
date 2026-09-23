"""The guided setup, in the terminal: docker compose run --rm setup (README, "Install").

It asks who writes the notes — a subscription, through its vendor's own program, or an API
key — then the sign-in or the key and the model, tries them with a one-word question, and writes
them into .env next to docker-compose.yml, the one place settings live: every other line of .env
stays as it was. Nothing is written before the last answer. Run it again to change provider, key
or model, or to update a vendor's program; anything else is edited in .env by hand.

A subscription's program is installed from its vendor into the accounts volume and signs in with
the vendor's own flow, here in the terminal: the sign-in stays with the program, never in .env,
and this app never sees it (report/program.py). Then the program's folder goes to the app's user.

The first time .env starts from .env.example, the data folders are made, and the setup fits
the app to this computer, as Docker sees it: threads, at most the CPUs there are (Docker
refuses a container that asks for more), and the speech model by free memory — speed never
decides it: the default runs faster than the lecture even on two slow cores (README, "Where
it runs"). The app runs as the owner of this folder (RECAP_USER), who also gets .env and the
data folders: on Linux that is you. Where the folder looks owned by root (rootless Docker,
Podman, Docker Desktop) root in the container is you, or Docker Desktop's virtual machine.

    python -m recap.setup FOLDER      FOLDER is where docker-compose.yml and .env live
"""
from __future__ import annotations

import getpass
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import report, settings
from .report import antigravity, claude, codex
from .report.openai_compatible import PRESETS
from .report.program import Program

TEMPLATE = Path(__file__).resolve().parent.parent / ".env.example"     # copied in by the Dockerfile
# The speech model for this computer: the first whose need fits the free memory, best first.
# GB: the measured peak for a 3-hour lecture (transcription.py) plus room for the rest.
SPEECH_MODELS = (("large-v3-turbo", 3.5), ("small", 2.5))
SHARED = ("REPORT_URL", "REPORT_API_KEY", "REPORT_MODEL")       # the same names for every provider
LOCAL = ("ollama", "lmstudio")       # they need no key


@dataclass(frozen=True)
class Choice:
    provider: str                       # REPORT_PROVIDER
    label: str
    program: Program | None = None      # a vendor's program, installed by the setup
    sign_in: str = ""                   # how its sign-in goes, for people; empty: no sign-in, a key


CHOICES = (
    Choice("claude", "Claude, with your Pro or Max subscription", claude.PROGRAM,
           "Claude Code's own sign-in starts: open the link it shows and sign in; if the browser then "
           "shows a code, paste it here."),
    Choice("claude", "Claude, with an Anthropic API key", claude.PROGRAM),
    Choice("codex", "ChatGPT, with your Plus, Pro or Business plan, through Codex", codex.PROGRAM,
           "Codex's own sign-in starts: open the link it shows, sign in to ChatGPT and type the one-time\n"
           "code. If the page says that signing in with a code is off, turn it on in ChatGPT's settings,\n"
           "under Security, and run the setup again."),
    Choice("antigravity", "Gemini, with your Google account (free, AI Pro or Ultra), through Antigravity",
           antigravity.PROGRAM,
           "Antigravity opens. Sign in with Google: open the link it shows and paste back the code.\n"
           "Before leaving, open its settings (type /) and turn off “Enable Telemetry”: with it on,\n"
           "Google may use your lectures to train its models and have people read them.\n"
           "Then leave with Ctrl+C."),
    Choice("openai", "OpenAI"),
    Choice("gemini", "Gemini (a free key: https://aistudio.google.com/apikey)"),
    Choice("openrouter", "OpenRouter (many models, some free)"),
    Choice("mistral", "Mistral"),
    Choice("deepseek", "DeepSeek"),
    Choice("ollama", "Ollama, on this computer"),
    Choice("lmstudio", "LM Studio, on this computer"),
    Choice("compatible", "another OpenAI-compatible server"),
)


class EnvFile:
    """.env as lines — .env.example's until the first save — whose values are read and replaced
    where they are: comments and order stay."""

    def __init__(self, path: Path):
        self.path = path
        self.new = not path.exists()
        self.lines = (TEMPLATE if self.new else path).read_text(encoding="utf-8").splitlines()

    def get(self, name: str) -> str:
        for line in self.lines:
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
        return ""

    def set(self, name: str, value: str) -> None:
        """The line NAME=…, or a commented #NAME=…, gets the value; otherwise it is appended."""
        for i, line in enumerate(self.lines):
            if re.match(rf"#?{name}=", line):
                self.lines[i] = f"{name}={value}"
                return
        self.lines.append(f"{name}={value}")

    def save(self, owner: tuple[int, int]) -> None:
        """Readable only by the owner: it holds the key."""
        partial = self.path.with_name(".env.partial")
        partial.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        os.chmod(partial, 0o600)
        _give(partial, owner)
        partial.replace(self.path)


def main() -> None:
    folder = Path(sys.argv[1])
    env = EnvFile(folder / ".env")
    info = folder.stat()
    owner = (info.st_uid, info.st_gid)

    if not env.new:
        print(f"Now the notes are written by: {env.get('REPORT_PROVIDER')} · "
              f"{env.get('REPORT_MODEL') or 'its default model'}")
    print("Who should write the notes?")
    for i, c in enumerate(CHOICES, 1):
        print(f"  {i:>2}) {c.label}")
    choice = CHOICES[_number("Choose a number", len(CHOICES)) - 1]
    values = _ask_for(choice, env)

    print("\nTrying it with a one-word question…")
    try:
        print(f"✓ {values['REPORT_MODEL'] or 'the default model'} answered: {_ping(values)[:60]}")
    except (RuntimeError, ValueError) as error:
        print(f"✗ It did not work: {error}")
        if not _yes("Save it anyway (for example if Ollama is not running yet)?"):
            print("Nothing saved. Run the setup again when ready.")
            sys.exit(1)
    if choice.program:
        choice.program.give(owner)

    for name, value in {**values, "RECAP_USER": f"{owner[0]}:{owner[1]}"}.items():
        env.set(name, value)
    if env.new:
        _fit(env)
    _data_folders(folder, env.get("RECAP_DATA") or "./data", owner)
    env.save(owner)
    print(f"\nSaved to .env. Start PoliTo Recap, or restart it with the new settings:\n"
          f"  docker compose up -d\nthen open http://localhost:{env.get('RECAP_PORT') or 8470}")


def _ask_for(choice: Choice, env: EnvFile) -> dict[str, str]:
    """The .env values for this choice, after installing and signing in its program if it has
    one. URL, key and model are offered again only if the provider stays the same: a key never
    goes to another provider's server. A subscription's choice clears the key: with a key, the
    key would pay."""
    kept = {name: env.get(name) if env.get("REPORT_PROVIDER") == choice.provider else "" for name in SHARED}
    values = {"REPORT_PROVIDER": choice.provider, "REPORT_URL": ""}
    if choice.program:
        print(f"\nInstalling {choice.program.title} from its vendor…")
        try:
            choice.program.install()
        except RuntimeError as error:
            _stop(str(error))
    if choice.sign_in:
        _sign_in(choice.program, choice.sign_in)
        values["REPORT_API_KEY"] = ""
    if choice.provider == "claude":
        if not choice.sign_in:
            values["REPORT_API_KEY"] = _secret("Anthropic API key", kept["REPORT_API_KEY"])
        values["REPORT_MODEL"] = _text("Model: opus or sonnet", kept["REPORT_MODEL"] or "opus")
        return values
    if choice.provider == "codex":
        values["REPORT_MODEL"] = _text("Model, as OpenAI names it (Enter: Codex's default)", kept["REPORT_MODEL"],
                                       needed=False)
        return values
    if choice.provider == "antigravity":
        try:
            options = antigravity.models()
        except RuntimeError as error:
            _stop(str(error))
        values["REPORT_MODEL"] = _choose("Model", options, kept["REPORT_MODEL"])
        return values
    preset = PRESETS[choice.provider]
    if choice.provider in LOCAL:
        url = _text("Where it runs (Enter: this computer)", kept["REPORT_URL"] or preset.url)
        values["REPORT_URL"] = "" if url == preset.url else url
        values["REPORT_API_KEY"] = ""
    elif choice.provider == "compatible":
        values["REPORT_URL"] = _text("The server's base URL, ending in /v1", kept["REPORT_URL"] or None)
        values["REPORT_API_KEY"] = _secret("API key", kept["REPORT_API_KEY"], needed=False)
    else:
        values["REPORT_API_KEY"] = _secret("API key", kept["REPORT_API_KEY"])
    values["REPORT_MODEL"] = _text("Model, as the provider names it", kept["REPORT_MODEL"] or preset.example or None)
    return values


def _sign_in(program: Program, how: str) -> None:
    """The vendor's own sign-in, in this terminal; the program keeps what it gets."""
    if program.signed_in() and not _yes(f"{program.title} is already signed in. Sign in again?"):
        return
    print(f"\n{how}\n")
    program.run(list(program.sign_in_args), interactive=True)
    if not program.signed_in():
        _stop(f"{program.title} is not signed in")


def _stop(problem: str) -> None:
    """The setup ends here, having written nothing."""
    print(f"✗ {problem}. Nothing saved: run the setup again to retry.")
    sys.exit(1)


def _ping(values: dict[str, str]) -> str:
    """The provider's answer with these values, which go into this process's environment over
    the current .env (docker-compose.yml passes it), as the app will have them."""
    os.environ.update(values)
    settings.load.cache_clear()
    chosen = settings.load()
    report.check(chosen)
    return report.PROVIDERS[chosen.report_provider].ping(chosen)


def _fit(env: EnvFile) -> None:
    """Threads and speech model for this computer (see the top)."""
    cpus = os.cpu_count() or 1
    threads = min(settings.THREADS, cpus)
    free = _free_memory()
    model = next((name for name, need in SPEECH_MODELS if free >= need), SPEECH_MODELS[-1][0])
    for name in ("RECAP_CPUS", "WHISPER_THREADS", "OCR_THREADS"):
        env.set(name, str(threads))
    env.set("WHISPER_MODEL", model)
    print(f"\nThis computer gives Docker {cpus} CPUs and {free:.1f} GB of free memory: "
          f"speech model {model}, {threads} threads.")
    if free < SPEECH_MODELS[-1][1]:
        print(f"That is too little memory: {model} needs {SPEECH_MODELS[-1][1]} GB free, and a long "
              "lecture can stop halfway. Close other programs, or give Docker more memory.")


def _free_memory() -> float:
    """GB the computer can still give (MemAvailable): in a container it is the host's, or
    Docker Desktop's virtual machine's."""
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 ** 2
    raise RuntimeError("/proc/meminfo has no MemAvailable")


def _data_folders(folder: Path, data: str, owner: tuple[int, int]) -> None:
    """courses/ and models/ in RECAP_DATA, given to the owner. A RECAP_DATA outside this folder
    cannot be seen from here: there you make them yourself."""
    root = (folder / data).resolve()
    if not root.is_relative_to(folder.resolve()):
        print(f"RECAP_DATA is {data}: make courses/ and models/ in it, owned by {owner[0]}:{owner[1]}.")
        return
    for sub in ("courses", "models"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for path in (root, root / "courses", root / "models"):
        _give(path, owner)


def _give(path: Path, owner: tuple[int, int]) -> None:
    """To the owner, unless it is theirs already: on Docker Desktop what the setup makes may
    already look like theirs, and changing owners there may be refused."""
    info = path.stat()
    if (info.st_uid, info.st_gid) != owner:
        os.chown(path, *owner)


def _text(question: str, default: str | None, needed: bool = True) -> str:
    """An answer; Enter takes the default, if there is one, or nothing if none is needed."""
    while True:
        answer = input(f"{question}{f' [{default}]' if default else ''}: ").strip() or default or ""
        if answer or not needed:
            return answer
        print("This one is needed.")


def _secret(question: str, current: str, needed: bool = True) -> str:
    """A key, typed without showing it; Enter keeps the current one, if there is one."""
    hint = " (Enter keeps the current one)" if current else "" if needed else " (Enter: none)"
    while True:
        answer = getpass.getpass(f"{question}{hint}, it will not show: ").strip() or current
        if answer or not needed:
            return answer
        print("This one is needed.")


def _choose(question: str, options: list[tuple[str, str]], current: str) -> str:
    """One of the (id, name) options, by number; Enter takes the current one, or the first."""
    for i, (_, name) in enumerate(options, 1):
        print(f"  {i:>2}) {name}")
    ids = [option_id for option_id, _ in options]
    default = ids.index(current) + 1 if current in ids else 1
    while True:
        answer = input(f"{question} [{default}]: ").strip() or str(default)
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return ids[int(answer) - 1]


def _number(question: str, highest: int) -> int:
    while True:
        answer = input(f"{question} (1-{highest}): ").strip()
        if answer.isdigit() and 1 <= int(answer) <= highest:
            return int(answer)


def _yes(question: str) -> bool:
    return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped: nothing saved.")
        sys.exit(1)
