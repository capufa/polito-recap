"""PoliTo Recap's settings: environment variables, that is the .env file next to
docker-compose.yml, plus HF_HOME, the models folder the Dockerfile sets. They are read only
here, once, with their defaults; the commented list for whoever installs it is .env.example,
and the setup (setup.py) writes who writes the notes. At startup the app checks what it can
without the network (numbers, the OCR size, the report provider and what it needs): with a
wrong one it starts nothing and its page says why (server.py), rather than failing after
half an hour of transcription. A wrong model name shows up only at the step that uses it.
A subscription's sign-in is not a setting: its vendor's program keeps it (report/program.py)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

OCR_MODELS = ("tiny", "small", "medium")
THREADS = 4      # CPU threads by default, and the most the setup gives: more is slower on CPUs with slow cores (transcription.py)
DEFAULT_UPDATE_URL = "https://api.github.com/repos/capufa/polito-recap/releases/latest"
VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"     # written by the Dockerfile


@dataclass(frozen=True)
class Settings:
    whisper_model: str          # faster-whisper name, Hugging Face id or folder
    whisper_compute_type: str   # int8, int8_float32, float32…
    whisper_threads: int
    ocr_threads: int
    ocr_model: str              # PP-OCRv6 size: tiny, small (built in), medium
    report_provider: str        # claude, codex, antigravity, or an OpenAI-compatible preset (report/)
    report_model: str
    report_url: str             # empty: the preset's own
    report_api_key: str         # any provider's key, Anthropic's too; empty for a subscription
    report_max_tokens: int      # tokens of the answer, at most (OpenAI-compatible providers only)
    hostnames: tuple[str, ...]  # names the app is reached by, besides IPs and localhost
    update_url: str             # where to ask for the latest version; empty: never ask (RECAP_UPDATE_URL=off)
    models: Path                # HF_HOME: Whisper's weights and the downloaded OCR models

    def summary(self) -> str:
        """One line for the startup logs: what the app will use, without the key."""
        return (f"report {self.report_provider} · {self.report_model}"
                + (f" · {self.report_url}" if self.report_url else "")
                + f" | Whisper {self.whisper_model} {self.whisper_compute_type}, {self.whisper_threads} threads"
                f" | OCR {self.ocr_model}, {self.ocr_threads} threads")


@lru_cache(maxsize=1)
def load() -> Settings:
    provider = _text("REPORT_PROVIDER", "claude")
    update_url = _text("RECAP_UPDATE_URL", DEFAULT_UPDATE_URL)
    settings = Settings(
        whisper_model=_text("WHISPER_MODEL", "large-v3-turbo"),
        whisper_compute_type=_text("WHISPER_COMPUTE_TYPE", "int8"),
        whisper_threads=_integer("WHISPER_THREADS", THREADS),
        ocr_threads=_integer("OCR_THREADS", THREADS),
        ocr_model=_text("OCR_MODEL", "small"),
        report_provider=provider,
        report_model=_text("REPORT_MODEL", "opus" if provider == "claude" else ""),
        report_url=_text("REPORT_URL", "").rstrip("/"),
        report_api_key=_text("REPORT_API_KEY", ""),
        report_max_tokens=_integer("REPORT_MAX_TOKENS", 32000),
        hostnames=tuple(n.strip().lower() for n in _text("RECAP_HOSTNAMES", "").split(",") if n.strip()),
        update_url="" if update_url == "off" else update_url,
        models=Path(os.environ["HF_HOME"]),
    )
    if settings.ocr_model not in OCR_MODELS:
        raise ValueError(f"OCR_MODEL={settings.ocr_model}: must be one of {', '.join(OCR_MODELS)}")
    return settings


def version() -> str:
    """This image's version; "dev" if built without one (from the source, by hand)."""
    return VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "dev"


def _text(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _integer(name: str, default: int) -> int:
    value = _text(name, str(default))
    if not value.isdigit() or int(value) < 1:
        raise ValueError(f"{name}={value}: must be a whole number from 1 up")
    return int(value)
