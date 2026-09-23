"""Seconds ↔ "HH:MM:SS". Timestamps in the JSON files and in the report always take this form."""


def hhmmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def seconds(text: str) -> int:
    h, m, s = (int(x) for x in text.split(":"))
    return h * 3600 + m * 60 + s


def readable(seconds: int) -> str:
    """A duration for people: 4952 → "1 h 22 min", 1320 → "22 min"."""
    hours, minutes = seconds // 3600, seconds % 3600 // 60
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"
