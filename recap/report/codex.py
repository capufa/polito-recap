"""The report with Codex (`codex exec`), OpenAI's own program, for a ChatGPT plan: Plus, Pro,
Business. Installed by the setup (program.py) at the vendor's latest version — newer OpenAI
models need a newer Codex — and signed in with Codex's own device sign-in: a link and a
one-time code (ChatGPT's security settings may have to allow it). Codex keeps the sign-in in a
file of its home, and renews it by rotating it: one Codex at a time, as the app's queue already
runs; the setup's test is best run while no lecture is being processed.

Everything goes in the input, the instructions too: with a ChatGPT sign-in Codex may ignore its
own instruction settings. The answer comes back in the fixed shape (--output-schema, OpenAI's
strict mode, which schema.json meets), from a read-only sandbox with every tool of its own off
(TOOLS, from `codex features list`). All the settings are checked (--strict-config): a name a
newer Codex no longer knows stops the run, instead of silently leaving a tool on. A message
holds at most MAX_CHARACTERS: the longest lecture so far is under half of it."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..settings import Settings
from .program import Program

PROGRAM = Program(
    "codex", "Codex", ".local/bin/codex", ".codex/auth.json", "https://chatgpt.com/codex/install.sh",
    shell="sh", sign_in_args=("login", "--device-auth", "-c", 'cli_auth_credentials_store="file"'),
    install_environment={"CODEX_NON_INTERACTIVE": "true"})
TIMEOUT = 3600                  # seconds: a lecture takes about ten minutes
MAX_CHARACTERS = 1_048_576      # of one message (codex-rs, protocol/src/user_input.rs)
SETTINGS = ("check_for_update_on_startup=false", 'cli_auth_credentials_store="file"', 'web_search="disabled"')
TOOLS = ("shell_tool", "unified_exec", "view_image", "multi_agent", "apps", "plugins", "browser_use",
         "in_app_browser", "computer_use", "image_generation", "hooks", "skill_search", "tool_suggest",
         "sleep_tool", "code_mode_host")


def check(settings: Settings) -> None:
    """At startup: Codex is there and signed in."""
    PROGRAM.check()


def generate(instructions: str, alignment: str, schema: dict, settings: Settings) -> str:
    message = instructions + "\n\nThe lecture, as JSON:\n" + alignment
    if len(message) > MAX_CHARACTERS:
        raise RuntimeError(f"the lecture is too long for Codex: {len(message):,} characters, at most {MAX_CHARACTERS:,}")
    return _exec(settings, message, schema)


def ping(settings: Settings) -> str:
    """The setup's test: a one-word question with this sign-in and model."""
    return _exec(settings, "Reply with the single word OK.").strip()


def _exec(settings: Settings, message: str, schema: dict | None = None) -> str:
    """codex exec with the message on stdin: its final answer, or an error that says why not."""
    with tempfile.TemporaryDirectory() as work:
        answer = Path(work) / "answer.txt"
        args = ["exec", "--strict-config", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
                "-o", str(answer)]
        for setting in SETTINGS:
            args += ["-c", setting]
        for tool in TOOLS:
            args += ["--disable", tool]
        if settings.report_model:
            args += ["-m", settings.report_model]
        if schema is not None:
            shape = Path(work) / "schema.json"
            shape.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            args += ["--output-schema", str(shape)]
        result = PROGRAM.run([*args, "-"], input=message, timeout=TIMEOUT)
        if result.returncode != 0 or not answer.is_file():
            raise RuntimeError(f"codex exec exited with {result.returncode}: "
                               f"{(result.stderr or result.stdout).strip()[-500:]}")
        return answer.read_text(encoding="utf-8")
