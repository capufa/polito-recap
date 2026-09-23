"""The report: alignment.json → a JSON of a fixed shape, written by a language model; and the
check that notices quote words that really exist in the transcript (Quotes). The model's
instructions live right here: prompt.md (how to behave) and schema.json (the shape; each
field's `description` is part of the instructions). The readable page is laid out by
`page`.

WHO WRITES IT is set by REPORT_PROVIDER (settings.py):
    claude        Claude Code (claude.py), with the subscription or an Anthropic key
    codex         Codex (codex.py), with a ChatGPT plan
    antigravity   Antigravity CLI (antigravity.py), with a Google account
    openai, openrouter, gemini, mistral, deepseek, ollama, lmstudio, compatible
                  an OpenAI-compatible API (openai_compatible.py, one preset each)
The first three run the vendor's own program, installed and signed in by the setup (program.py).
All of them get the same instructions and the same JSON, and the answer is parsed and
checked against the schema here. A malformed answer gets one more try, told what was
wrong; a second one is a lecture error (it gets resumed), never a half-built page.

The schema's `description`s go through the model's safeguards like any other text: an
innocent wording can get blocked ("Opus 5's safeguards flagged this message", zero output
tokens). It happened (in the Italian schema) with "the span's from field, copied" + "clean
and unabridged": if it happens again, reword the description and retry.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from ..settings import Settings, load
from ..timecode import seconds
from . import antigravity, claude, codex, openai_compatible

HERE = Path(__file__).resolve().parent
PROMPT = HERE / "prompt.md"
SCHEMA = HERE / "schema.json"
PROVIDERS = {"claude": claude, "codex": codex, "antigravity": antigravity,
             **{name: openai_compatible for name in openai_compatible.PRESETS}}
ATTEMPTS = 2
TOLERANCE_SECONDS = 3     # a quoted timestamp must fall within this of a transcript word
_FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```\s*$", re.DOTALL)     # some models wrap JSON in markdown


def check(settings: Settings) -> None:
    """At startup: the provider exists and has what it needs."""
    if settings.report_provider not in PROVIDERS:
        raise ValueError(f"REPORT_PROVIDER={settings.report_provider}: must be one of {', '.join(PROVIDERS)}")
    PROVIDERS[settings.report_provider].check(settings)


def generate(alignment: dict) -> dict:
    """The structured report, from the chosen provider, checked against the schema."""
    settings = load()
    provider = PROVIDERS[settings.report_provider]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    instructions = PROMPT.read_text(encoding="utf-8")
    text = json.dumps(alignment, ensure_ascii=False)
    feedback = ""
    for _ in range(ATTEMPTS):
        report, problem = _parse(provider.generate(instructions + feedback, text, schema, settings), validator)
        if report is not None:
            return report
        feedback = (f"\n\nYour previous answer was rejected ({problem}): answer again with the whole JSON, "
                    "exactly as the schema asks.")
    raise RuntimeError(f"the notes from {settings.report_model} do not have the right shape: {problem}")


def _parse(text: str, validator: Draft202012Validator) -> tuple[dict | None, str]:
    """The report and "", or None and what is wrong with it."""
    fence = _FENCE.match(text.strip())
    try:
        report = json.loads(fence.group(1) if fence else text)
    except json.JSONDecodeError as error:
        return None, f"not JSON: {error}"
    error = next(validator.iter_errors(report), None)
    if error is not None:
        return None, f"{'/'.join(str(p) for p in error.absolute_path) or 'root'}: {error.message}"
    return report, ""


class Quotes:
    """The transcript as normalized text and as a list of instants, to check that a quote
    really exists and that its timestamp falls where someone is speaking."""

    def __init__(self, transcript: list[dict]):
        self._text = _normalize(" ".join(s["text"] for s in transcript))
        self._instants = sorted(w["start"] for s in transcript for w in s["words"])

    def problem(self, item: dict) -> str | None:
        """None if the item holds up; otherwise the reason for doubt."""
        t = seconds(item["t"])
        if not any(abs(i - t) <= TOLERANCE_SECONDS for i in self._instants):
            return "no speech at that timestamp"
        if _normalize(item["quote"]) not in self._text:
            return "quote not found"
        return None


def _normalize(text: str) -> str:
    """Lowercase, no punctuation, single spaces: so "Ok, it's the exam." and "ok it s the exam" match."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())
