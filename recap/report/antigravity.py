"""The report with Antigravity CLI (`agy`), Google's own program for a Google account — free,
AI Pro or AI Ultra: since 18 June 2026 Gemini CLI no longer serves personal accounts. Installed
by the setup (program.py) and signed in inside the program itself; the model is one of those
the account offers (`agy models`), chosen in the setup.

Antigravity is an agent, and that shapes the request (measured with version 1.2.9):
- a long message is cut at about 192,000 characters, without a word (half of a two-hour
  lecture): so the lecture goes in a file of an empty workspace, and the instructions say to
  read all of it, in parts, with its file tool;
- left to itself it runs commands, which are denied here, and ends with an empty answer marked
  SUCCESS: the instructions allow no tool but reading that file;
- the shape is enforced (--json-schema) and comes back in the result event's structured_output.
An answer that is not SUCCESS with notes is an error, and so are notes whose latest timestamp
falls well before the end of the lecture: it was read only in part.

On a personal account Google may use what it receives to train its models and have people read
it, unless "Enable Telemetry" is off in the program's settings, for the whole account (README).
The program never updates itself while the app runs; the setup installs the latest."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from ..settings import Settings
from ..timecode import readable, seconds
from .program import Program

PROGRAM = Program(
    "antigravity", "Antigravity CLI", ".local/bin/agy", ".gemini/antigravity-cli/antigravity-oauth-token",
    "https://antigravity.google/cli/install.sh", environment={"AGY_CLI_DISABLE_AUTO_UPDATE": "true"})
TIMEOUT = 3600          # seconds: a lecture takes about ten minutes
COVERAGE = 0.75         # the notes' latest timestamp, as a share of the lecture: below, it was read in part
READ = ("\n\nThe lecture is in the file {path} (absolute path), as JSON, one item per line. It is long: "
        "read ALL of it, in consecutive parts, with your file-reading tool, from the first line to the "
        "last, before answering. Do not run commands, do not browse, do not write files: reading that "
        "file is the only tool you need. Then answer directly with the JSON.")
_TIME = re.compile(r"\b\d{2}:\d{2}:\d{2}\b")


def check(settings: Settings) -> None:
    """At startup: Antigravity CLI is there and signed in."""
    PROGRAM.check()


def models() -> list[tuple[str, str]]:
    """The models this account may use, as `agy models` lists them: (id, name)."""
    result = PROGRAM.run(["models"], timeout=120)
    found = [tuple(line.split("\t", 1)) for line in result.stdout.splitlines() if "\t" in line]
    if not found:
        raise RuntimeError(f"agy models listed nothing: {(result.stderr or result.stdout).strip()[-300:]}")
    return found


def generate(instructions: str, alignment: str, schema: dict, settings: Settings) -> str:
    lecture = json.loads(alignment)
    with tempfile.TemporaryDirectory() as workspace:
        path = Path(workspace) / "lecture.json"
        path.write_text(json.dumps(lecture, ensure_ascii=False, indent=1), encoding="utf-8")
        final = _turn(settings, instructions + READ.format(path=path), Path(workspace), schema)
    report = final.get("structured_output")
    if final.get("status") != "SUCCESS" or report is None:
        raise RuntimeError(f"Antigravity gave no notes ({final.get('status')}): "
                           f"{str(final.get('error') or final.get('response') or 'an empty answer')[:500]}")
    duration = seconds(lecture["lecture"]["duration"])
    latest = max((seconds(t) for t in _TIME.findall(json.dumps(report))), default=0)
    if latest < COVERAGE * duration:
        raise RuntimeError(f"Antigravity read only part of the lecture: its notes stop at {readable(latest)} "
                           f"of {readable(duration)}")
    return json.dumps(report, ensure_ascii=False)


def ping(settings: Settings) -> str:
    """The setup's test: a one-word question with this sign-in and model."""
    final = _turn(settings, "Reply with the single word OK.")
    if final.get("status") != "SUCCESS":
        raise RuntimeError(f"agy: {final.get('error') or final.get('status')}")
    return str(final.get("response", "")).strip()


def _turn(settings: Settings, message: str, workspace: Path | None = None, schema: dict | None = None) -> dict:
    """One message on stdin, as stream-json (plain text on stdin is not read), and the result
    event back; an error that says why if there is none."""
    args = ["--input-format", "stream-json", "--output-format", "stream-json"]
    if settings.report_model:
        args += ["--model", settings.report_model]
    if schema:
        args += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    line = json.dumps({"event": "user", "message": {"content": message}}, ensure_ascii=False) + "\n"
    result = PROGRAM.run(args, input=line, cwd=workspace, timeout=TIMEOUT)
    events = [json.loads(e) for e in result.stdout.splitlines() if e.startswith("{")]
    final = next((e["result"] for e in events if e.get("event") == "result"), None)
    if final is None:
        raise RuntimeError(f"agy exited with {result.returncode}: {result.stderr.strip()[-500:]}")
    return final
