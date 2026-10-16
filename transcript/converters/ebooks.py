"""Ebooks with Calibre's ebook-convert (when installed): Kindle MOBI/AZW3, EPUB, FB2..."""

from __future__ import annotations

from pathlib import Path

from .. import tools
from .base import Converter, Edge

SOURCES = ("epub", "mobi", "azw3", "fb2", "docx", "odt", "rtf", "html", "pdf", "cbz", "txt")
TARGETS = ("epub", "mobi", "azw3", "fb2", "pdf", "docx", "txt", "rtf")
KINDLE = {"mobi", "azw3"}


class CalibreConverter(Converter):
    name = "Calibre"
    hint = "https://calibre-ebook.com/download  ·  Windows: winget install calibre.calibre  ·  Linux: sudo apt install calibre"

    def available(self) -> bool:
        return tools.ebook_convert() is not None

    def details(self) -> str:
        return tools.ebook_convert() or ""

    def edges(self):
        # Calibre is the only way in or out of Kindle formats; for the rest pandoc and
        # LibreOffice are usually better, so it gets a higher cost.
        return self.matrix(SOURCES, TARGETS, lambda s, d: 1.0 if s in KINDLE or d in KINDLE else 2.0)

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        ctx.run([tools.ebook_convert(), str(src), str(dst)], timeout=1800)
        return dst
