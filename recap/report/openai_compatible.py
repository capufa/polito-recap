"""The report from an OpenAI-compatible API: POST <url>/chat/completions. OpenAI, Gemini,
OpenRouter (which reaches almost every model, open ones too), Mistral, DeepSeek, and locally
Ollama and LM Studio all speak it, each with its own dialect: the PRESETS below. Checked
against each provider's documentation in September 2026.

The report's shape is asked for twice: with response_format, where the provider supports a
JSON schema (DeepSeek only takes plain JSON mode), and as text in the instructions, which
every model reads. What comes back is only checked here for the transport — errors, a
refusal, a cut answer, an input cut short without a word — and returned as text:
report/__init__.py parses it and checks the schema. ping is the setup's test: one tiny
question, same request path."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..settings import Settings

TIMEOUT = 3600       # seconds: a slow local model can take a long time
CHARS_PER_TOKEN = 4  # a rough count of the input, to notice when a server silently cut it
PING_TOKENS = 1024   # room for the test's "OK": reasoning models think before answering


@dataclass(frozen=True)
class Preset:
    url: str                   # base URL; empty: REPORT_URL is required
    output: str                # how to ask for JSON: "json_schema", or "json_object" without a schema
    tokens_field: str          # the name of the answer-length limit
    example: str = ""          # a model to offer in the setup; empty: the user names it
    extra: dict = field(default_factory=dict)       # more fields of the request body
    headers: dict = field(default_factory=dict)


PRESETS = {
    # GPT-5 and the o-series refuse max_tokens.
    "openai": Preset("https://api.openai.com/v1", "json_schema", "max_completion_tokens", "gpt-5"),
    # Without require_parameters OpenRouter may route to a provider that drops the schema.
    "openrouter": Preset("https://openrouter.ai/api/v1", "json_schema", "max_tokens", "google/gemini-3.8-flash",
                         extra={"provider": {"require_parameters": True}},
                         headers={"HTTP-Referer": "https://github.com/capufa/polito-recap",
                                  "X-OpenRouter-Title": "PoliTo Recap"}),
    "gemini": Preset("https://generativelanguage.googleapis.com/v1beta/openai", "json_schema", "max_tokens",
                     "gemini-3.8-flash"),
    "mistral": Preset("https://api.mistral.ai/v1", "json_schema", "max_tokens", "mistral-large-latest"),
    "deepseek": Preset("https://api.deepseek.com", "json_object", "max_tokens", "deepseek-v4-pro"),
    # On the host, seen from the container (docker-compose.yml maps host.docker.internal).
    "ollama": Preset("http://host.docker.internal:11434/v1", "json_schema", "max_tokens"),
    "lmstudio": Preset("http://host.docker.internal:1234/v1", "json_schema", "max_tokens"),
    "compatible": Preset("", "json_schema", "max_tokens"),
}


def check(settings: Settings) -> None:
    """At startup: what this provider needs is there."""
    if not settings.report_model:
        raise ValueError(f"REPORT_PROVIDER={settings.report_provider} needs REPORT_MODEL (see .env.example)")
    if not (settings.report_url or PRESETS[settings.report_provider].url):
        raise ValueError(f"REPORT_PROVIDER={settings.report_provider} needs REPORT_URL (see .env.example)")


def generate(instructions: str, alignment: str, schema: dict, settings: Settings) -> str:
    preset = PRESETS[settings.report_provider]
    shape = ("\n\nAnswer with one JSON object, and nothing else, that follows this JSON schema:\n"
             + json.dumps(schema, ensure_ascii=False))
    messages = [{"role": "system", "content": instructions + shape}, {"role": "user", "content": alignment}]
    return _ask(settings, messages, settings.report_max_tokens,
                {"response_format": {"type": "json_schema", "json_schema": {"name": "report", "strict": True,
                                                                             "schema": schema}}
                 if preset.output == "json_schema" else {"type": "json_object"}})


def ping(settings: Settings) -> str:
    """The setup's test: the provider answers a one-word question with this key and model."""
    return _ask(settings, [{"role": "user", "content": "Reply with the single word OK."}], PING_TOKENS, {})


def _ask(settings: Settings, messages: list[dict], max_tokens: int, fields: dict) -> str:
    """POST <url>/chat/completions in the preset's dialect; the answer's text."""
    preset = PRESETS[settings.report_provider]
    body = {"model": settings.report_model, "messages": messages, preset.tokens_field: max_tokens,
            **fields, **preset.extra}
    headers = {"Content-Type": "application/json", **preset.headers}
    if settings.report_api_key:
        headers["Authorization"] = f"Bearer {settings.report_api_key}"
    url = f"{settings.report_url or preset.url}/chat/completions"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{url} answered {error.code}: {_message(error.read())}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"{url} is not responding: {error.reason}") from None
    return _content(result, "".join(m["content"] for m in messages), settings)


def _content(result: dict, sent: str, settings: Settings) -> str:
    """The answer's text, or an error that says what went wrong."""
    model = settings.report_model
    if "error" in result or not result.get("choices"):           # OpenRouter: a failure can come with HTTP 200
        raise RuntimeError(f"{model}: {_message(json.dumps(result).encode())}")
    choice = result["choices"][0]
    reason = (choice.get("finish_reason") or "stop").lower()
    if reason == "length":
        raise RuntimeError(f"{model} ran out of room before finishing: raise REPORT_MAX_TOKENS "
                           f"(now {settings.report_max_tokens}), within what the model allows")
    if reason != "stop":
        raise RuntimeError(f"{model} stopped early ({reason})")
    message = choice.get("message") or {}
    if message.get("refusal"):
        raise RuntimeError(f"{model} refused: {message['refusal']}")
    read = (result.get("usage") or {}).get("prompt_tokens")
    expected = len(sent) // CHARS_PER_TOKEN
    if read and read < expected // 3:
        raise RuntimeError(f"{model} read only {read} tokens of about {expected}: its context is too short "
                           "(for Ollama raise OLLAMA_CONTEXT_LENGTH, README)")
    text = (message.get("content") or "").strip()
    if not text:
        raise RuntimeError(f"{model} gave an empty answer")
    return text


def _message(raw: bytes) -> str:
    """The API's message, in the usual format ({"error": {"message"}}), or the raw answer."""
    text = raw.decode("utf-8", "replace")
    try:
        detail = json.loads(text)["error"]
        return detail["message"] if isinstance(detail, dict) else str(detail)
    except (ValueError, KeyError, TypeError):
        return text[:500]
