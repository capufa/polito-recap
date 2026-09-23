"""OCR of a screen without slides (another deck, a web page, the IDE), with RapidOCR.

Only for the segments that match no page of the PDFs: there the on-screen text cannot be
taken exactly, so it is read from the full frame.

The model is PP-OCRv6, multilingual: it reads Italian accents (à è ì ò ù), which the older
PP-OCRv4 default dropped. Size and threads are settings (OCR_*, settings.py): small ships
inside the package; tiny and medium are downloaded on first use into the models folder.
Measured on 10 lecture screens, 4 threads on the fast cores of an i5-12600H: tiny 0.8 s per
screen, small 1.9 s, medium 27.5 s; on 4 slow cores tiny 1.1 s, small 5.1 s. tiny and small
differ from medium in 6-8% of the characters, and small missed two screens holding one short
line, tiny none: a hint that tiny could be the default, on too few screens to switch.
Automatic threads also take the slow cores: with PP-OCRv4, 5.8 s against 1.9 s with 4.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from rapidocr import ModelType, RapidOCR

from . import settings


@lru_cache(maxsize=1)
def _engine() -> RapidOCR:
    chosen = settings.load()
    params = {"Global.use_cls": False,                  # on-screen text is upright
              "Global.log_level": "warning",
              "EngineConfig.onnxruntime.intra_op_num_threads": chosen.ocr_threads,
              "Det.model_type": ModelType(chosen.ocr_model),
              "Rec.model_type": ModelType(chosen.ocr_model)}
    if chosen.ocr_model != "small":                     # the others are downloaded, next to Whisper's
        params["Global.model_root_dir"] = str(chosen.models / "rapidocr")
    return RapidOCR(params=params)


def read(png: Path) -> str:
    """The lines of text in reading order (top down, left to right), one per line."""
    result = _engine()(str(png))
    if not result.txts:
        return ""
    lines = sorted(zip(result.boxes, result.txts), key=lambda r: (round(r[0][0][1] / 20), r[0][0][0]))  # y in 20 px bands, then x
    return "\n".join(text for _, text in lines)
