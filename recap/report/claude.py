"""The report with Claude Code, Anthropic's own program (`claude -p`), installed by the setup
into the accounts volume (program.py). Two ways to pay: the Pro or Max subscription, signed in
with Claude Code's own `claude auth login` in the setup (Claude Code keeps the sign-in and
renews it), or an Anthropic API key (REPORT_API_KEY), handed to Claude Code only when set: then
the key pays. It replaces its own system prompt with the instructions, runs without tools and
without the settings of its folder, and answers in the fixed shape (--json-schema, which Claude
Code enforces and retries on its own): reads stdin, answers, exits. It keeps no copy of the
session: its home is in a volume that lasts, and a session holds the whole lecture.

ping is the setup's test: one tiny question with the same sign-in.

VERSION is pinned, and Claude Code never updates itself: it plans to make --bare the default
for -p, and bare mode ignores the subscription's sign-in. Check that before raising it."""
from __future__ import annotations

import json

from ..settings import Settings
from .program import Program

VERSION = "2.1.259"
PROGRAM = Program(
    "claude", "Claude Code", ".local/bin/claude", ".claude/.credentials.json", "https://claude.ai/install.sh",
    version=VERSION, sign_in_args=("auth", "login", "--claudeai"),
    environment={"DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
TIMEOUT = 3600       # seconds: a long report takes about ten minutes


def check(settings: Settings) -> None:
    """At startup: Claude Code is there, signed in unless an API key pays."""
    PROGRAM.check(signed_in=not settings.report_api_key)


def generate(instructions: str, alignment: str, schema: dict, settings: Settings) -> str:
    answer = _ask(settings, alignment, "--tools", "", "--system-prompt", instructions,
                  "--json-schema", json.dumps(schema, ensure_ascii=False))
    if answer.get("structured_output") is None:
        raise RuntimeError(f"claude -p did not return the report ({answer.get('subtype', 'error')}): "
                           f"{str(answer.get('result', ''))[:500]}")
    return json.dumps(answer["structured_output"], ensure_ascii=False)


def ping(settings: Settings) -> str:
    """The setup's test: Claude answers a one-word question with this sign-in and model.
    No retries: Claude Code retries a rejected sign-in for about three minutes."""
    return str(_ask(settings, "Reply with the single word OK.", "--tools", "",
                    CLAUDE_CODE_MAX_RETRIES="0").get("result", "")).strip()


def _ask(settings: Settings, prompt: str, *options: str, **variables: str) -> dict:
    """claude -p with the prompt on stdin, and these environment variables on top: its JSON
    answer, or an error that says why not (a failure is JSON too, with the reason in result)."""
    key = {"ANTHROPIC_API_KEY": settings.report_api_key} if settings.report_api_key else {}
    result = PROGRAM.run(["-p", "--model", settings.report_model, "--output-format", "json",
                          "--setting-sources", "user", "--no-session-persistence", *options],
                         input=prompt, timeout=TIMEOUT, extra={**key, **variables})
    try:
        answer = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p exited with {result.returncode}: "
                           f"{result.stderr.strip() or result.stdout.strip()[:500]}") from None
    if result.returncode != 0 or answer.get("is_error"):
        raise RuntimeError(f"claude -p failed: {str(answer.get('result') or answer.get('subtype', 'error'))[:500]}")
    return answer
