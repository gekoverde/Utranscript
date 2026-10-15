"""OCR: text from images (and scanned PDFs) with Tesseract, when installed."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from .. import i18n, tools
from .base import ConversionError, Converter, Edge
from .images import pillow_formats, register_plugins

# ISO 639-1 (what users type) -> Tesseract language codes.
# fmt: off
TESSERACT_LANGS = {
    "es": "spa", "en": "eng", "fr": "fra", "de": "deu", "it": "ita", "pt": "por", "ca": "cat",
    "eu": "eus", "gl": "glg", "nl": "nld", "ru": "rus", "pl": "pol", "uk": "ukr", "ja": "jpn",
    "zh": "chi_sim", "ko": "kor", "ar": "ara", "tr": "tur", "sv": "swe", "da": "dan", "fi": "fin",
    "no": "nor", "cs": "ces", "el": "ell", "he": "heb", "hi": "hin", "ro": "ron", "hu": "hun",
}
# fmt: on


@cache
def installed_languages() -> frozenset[str]:
    try:
        out = tools.run([tools.tesseract(), "--list-langs"]).stdout
    except ConversionError:
        return frozenset()
    return frozenset(line.strip() for line in out.splitlines()[1:] if line.strip())


def languages(requested: str | None) -> str:
    available = installed_languages()
    if requested:
        wanted = [TESSERACT_LANGS.get(code.strip(), code.strip()) for code in requested.replace(",", "+").split("+")]
    else:
        wanted = [TESSERACT_LANGS.get(i18n.LANG, "eng"), "eng"]
    chosen = [code for code in dict.fromkeys(wanted) if not available or code in available]
    return "+".join(chosen) or "eng"


class OcrConverter(Converter):
    name = "Tesseract OCR"
    hint = "Windows: winget install UB-Mannheim.TesseractOCR  ·  Linux: sudo apt install tesseract-ocr tesseract-ocr-spa"

    def available(self) -> bool:
        return tools.tesseract() is not None

    def details(self) -> str:
        langs = ", ".join(sorted(installed_languages()))
        return f"{tools.tesseract()} · {langs}"

    def edges(self):
        readable, _ = pillow_formats()
        return [self.edge(fmt, "txt", cost=3.0) for fmt in sorted(readable)]

    def read_image(self, image, ctx) -> str:
        """Run OCR on a Pillow image and return the text."""
        work = ctx.scratch("ocr")
        source = work / "page.png"
        image.save(source, "PNG")
        ctx.run([tools.tesseract(), str(source), str(work / "page"), "-l", languages(ctx.options.lang)], timeout=600)
        return (work / "page.txt").read_text(encoding="utf-8", errors="replace").strip()

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        from PIL import Image, ImageOps, ImageSequence

        register_plugins()
        texts = []
        with Image.open(src) as im:
            for frame in ImageSequence.Iterator(im):
                page = ImageOps.exif_transpose(frame.copy()) or frame.copy()
                if page.mode not in ("RGB", "L"):
                    page = page.convert("RGB")
                texts.append(self.read_image(page, ctx))
                if im.format not in ("TIFF", "MPO"):
                    break
        dst.write_text("\n\n\f".join(texts) + "\n", encoding="utf-8")
        return dst
