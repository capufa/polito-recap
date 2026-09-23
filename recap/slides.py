"""The lecturer's PDFs: the exact text of every page, and the render for the comparison with
the frames and for the lecture page."""
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image


@dataclass
class SlidePage:
    deck: str
    number: int          # 1-based, as the student sees it
    title: str           # the first line of text that is not a page number
    text: str


class Deck:
    """An open PDF: its pages and their render."""

    def __init__(self, pdf: Path):
        self.name = pdf.stem
        self._doc = fitz.open(pdf)
        self.pages = [SlidePage(self.name, i + 1, _title(p.get_text()), p.get_text().strip())
                      for i, p in enumerate(self._doc)]

    def render(self, number: int, dpi: int, color: bool = False) -> Image.Image:
        """The page at the requested resolution: grayscale for the comparison with the
        frames (there color is noise), in color for the lecture page."""
        space, mode = (fitz.csRGB, "RGB") if color else (fitz.csGRAY, "L")
        pix = self._doc[number - 1].get_pixmap(dpi=dpi, colorspace=space)
        return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def _title(text: str) -> str:
    lines = [r.strip() for r in text.splitlines() if r.strip() and not r.strip().isdigit()]
    return lines[0] if lines else ""
