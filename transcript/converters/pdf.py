"""PDF: text extraction and page rendering with PDFium, comic books (CBZ)."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .base import ConversionError, Converter, Edge
from .images import PILLOW_NAMES, SAVE_PARAMS, flatten, register_plugins

PAGE_IMAGE_TARGETS = ("png", "jpg", "webp", "tiff", "bmp")
COMIC_IMAGES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".heic", ".tif", ".tiff")


def natural_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def open_pdf(src: Path):
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(str(src))
    except pdfium.PdfiumError as exc:
        message = str(exc)
        if "password" in message.lower():
            message = "the PDF is password protected"
        raise ConversionError(f"cannot open the PDF: {message}") from exc


def render_pages(src: Path, dpi: int):
    """Yield every page of a PDF as a Pillow image."""
    pdf = open_pdf(src)
    try:
        for page in pdf:
            try:
                yield page.render(scale=dpi / 72).to_pil()
            finally:
                page.close()
    finally:
        pdf.close()


class PdfConverter(Converter):
    name = "PDFium"

    def details(self) -> str:
        from pypdfium2.version import PYPDFIUM_INFO

        return f"pypdfium2 {PYPDFIUM_INFO}"

    def edges(self):
        edges = [self.edge("pdf", "txt")]
        edges += [self.edge("pdf", fmt, terminal=True) for fmt in PAGE_IMAGE_TARGETS]
        edges += [self.edge("pdf", "cbz", terminal=True), self.edge("cbz", "pdf", terminal=True)]
        return edges

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        if edge.src == "cbz":
            return self._comic_to_pdf(src, dst)
        if edge.dst == "txt":
            return self._to_text(src, dst, ctx)
        if edge.dst == "cbz":
            return self._to_comic(src, dst, ctx)
        return self._to_images(src, dst, edge.dst, ctx)

    def _to_text(self, src: Path, dst: Path, ctx) -> Path:
        pdf = open_pdf(src)
        pages = []
        try:
            total = len(pdf)
            for index, page in enumerate(pdf):
                textpage = page.get_textpage()
                pages.append(textpage.get_text_bounded().replace("\r\n", "\n").strip())
                textpage.close()
                page.close()
                ctx.progress(index + 1, total)
        finally:
            pdf.close()
        text = "\n\n\f".join(pages).strip()
        if not text:
            # A scanned PDF has no text layer: read it with OCR when Tesseract is installed.
            from .ocr import OcrConverter

            ocr = OcrConverter()
            if not ocr.available():
                raise ConversionError(f"the PDF has no text layer (it looks scanned); reading it needs Tesseract OCR: {ocr.hint}")
            ctx.log("no text layer found, running OCR")
            text = "\n\n\f".join(ocr.read_image(img, ctx) for img in render_pages(src, 300)).strip()
            if not text:
                raise ConversionError("the PDF has no text layer and OCR did not find any text in it")
        dst.write_text(text + "\n", encoding="utf-8")
        return dst

    def _to_images(self, src: Path, dst: Path, target: str, ctx) -> Path:
        dpi = ctx.options.dpi
        pdf = open_pdf(src)
        total = len(pdf)
        pdf.close()
        fmt = PILLOW_NAMES[target]
        params = SAVE_PARAMS.get(target, {})
        if target == "tiff":  # TIFF keeps every page in a single file
            pages = [img for img in render_pages(src, dpi)]
            pages[0].save(dst, fmt, save_all=True, append_images=pages[1:], **params)
            return dst
        if total == 1:
            img = list(render_pages(src, dpi))[0]
            (flatten(img) if target in ("jpg", "bmp") else img).save(dst, fmt, **params)
            return dst
        folder = dst.with_suffix("")
        folder.mkdir()
        width = max(3, len(str(total)))
        for index, img in enumerate(render_pages(src, dpi), 1):
            page = folder / f"{folder.name}-{index:0{width}d}{dst.suffix}"
            (flatten(img) if target in ("jpg", "bmp") else img).save(page, fmt, **params)
            ctx.progress(index, total)
        return folder

    def _to_comic(self, src: Path, dst: Path, ctx) -> Path:
        pdf = open_pdf(src)
        total = len(pdf)
        pdf.close()
        width = max(3, len(str(total)))
        scratch = ctx.scratch("pages")
        with zipfile.ZipFile(dst, "w") as zf:
            for index, img in enumerate(render_pages(src, ctx.options.dpi), 1):
                page = scratch / f"{index:0{width}d}.jpg"
                flatten(img).save(page, "JPEG", quality=90)
                zf.write(page, page.name)
                page.unlink()
                ctx.progress(index, total)
        return dst

    def _comic_to_pdf(self, src: Path, dst: Path) -> Path:
        from PIL import Image

        register_plugins()
        images = []
        with zipfile.ZipFile(src) as zf:
            names = sorted(
                (n for n in zf.namelist() if n.lower().endswith(COMIC_IMAGES) and not n.startswith("__MACOSX")),
                key=natural_key,
            )
            for name in names:
                with zf.open(name) as fh:
                    img = Image.open(fh)
                    img.load()
                    images.append(flatten(img))
        if not images:
            raise ConversionError("the comic book does not contain any image")
        images[0].save(dst, "PDF", save_all=True, append_images=images[1:], resolution=150.0)
        return dst
