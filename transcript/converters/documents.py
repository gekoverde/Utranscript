"""Documents with pandoc: Markdown, HTML, Word, OpenDocument, EPUB, LaTeX, Typst..."""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path

from .. import i18n, tools
from .base import Converter, Edge

# Our format id -> (pandoc reader, pandoc writer).
PANDOC_FORMATS: dict[str, tuple[str | None, str | None]] = {
    "md": ("markdown", "gfm"),
    "html": ("html", "html5"),
    "docx": ("docx", "docx"),
    "odt": ("odt", "odt"),
    "rtf": ("rtf", "rtf"),
    "epub": ("epub", "epub3"),
    "tex": ("latex", "latex"),
    "typ": ("typst", "typst"),
    "rst": ("rst", "rst"),
    "adoc": ("asciidoc", "asciidoc"),
    "org": ("org", "org"),
    "textile": ("textile", "textile"),
    "wiki": ("mediawiki", "mediawiki"),
    "dbk": ("docbook", "docbook5"),
    "ipynb": ("ipynb", "ipynb"),
    "opml": ("opml", "opml"),
    "fb2": ("fb2", "fb2"),
    "pptx": ("pptx", "pptx"),
    "csv": ("csv", None),
    "tsv": ("tsv", None),
    "txt": (None, "plain"),
    "pdf": (None, "pdf"),
}

STANDALONE = {"html", "tex", "rtf", "typ", "dbk", "opml", "fb2", "epub"}
TEXT_WRITERS = {"md", "rst", "adoc", "org", "textile", "wiki", "tex", "typ", "dbk", "ipynb"}
OFFICE = {"docx", "odt", "rtf"}
PDF_ENGINES = ("xelatex", "lualatex", "tectonic", "pdflatex", "typst", "weasyprint", "wkhtmltopdf")


@cache
def pandoc_info() -> tuple[tuple[int, ...], frozenset[str], frozenset[str]]:
    exe = tools.pandoc()
    version = tools.run([exe, "--version"]).stdout.split("\n", 1)[0]
    numbers = tuple(int(n) for n in re.findall(r"\d+", version)[:3])
    readers = frozenset(tools.run([exe, "--list-input-formats"]).stdout.split())
    writers = frozenset(tools.run([exe, "--list-output-formats"]).stdout.split())
    return numbers, readers, writers


@cache
def pdf_engine() -> str | None:
    for engine in PDF_ENGINES:
        if tools.find_program([engine]):
            return engine
    return None


class PandocConverter(Converter):
    name = "pandoc"
    hint = "pip install pypandoc_binary  ·  or install pandoc from https://pandoc.org"

    def available(self) -> bool:
        return tools.pandoc() is not None

    def details(self) -> str:
        version = ".".join(map(str, pandoc_info()[0]))
        engine = pdf_engine()
        return f"pandoc {version} · {tools.pandoc()}" + (f" · PDF engine: {engine}" if engine else "")

    def edges(self):
        _, readers, writers = pandoc_info()
        sources = [f for f, (r, _) in PANDOC_FORMATS.items() if r and r in readers]
        targets = [f for f, (_, w) in PANDOC_FORMATS.items() if w and w in writers and f != "pdf"]
        if "pdf" in writers and pdf_engine():
            targets.append("pdf")

        def cost(src: str, dst: str) -> float:
            if src in OFFICE and dst in OFFICE:
                return 1.5  # LibreOffice keeps the layout better when installed
            if dst in ("pptx", "opml"):
                return 2.0
            if dst == "pdf":
                return 1.2
            return 1.0

        return self.matrix(sources, targets, cost)

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        reader = PANDOC_FORMATS[edge.src][0]
        writer = PANDOC_FORMATS[edge.dst][1]
        version = pandoc_info()[0]
        cmd = [tools.pandoc(), str(src.resolve()), "-f", reader, "-t", writer, "-o", dst.name]
        cmd.append(f"--resource-path={src.resolve().parent}{os.pathsep}.")
        if edge.dst in STANDALONE:
            cmd.append("--standalone")
        if edge.dst == "html":
            cmd.append("--embed-resources" if version >= (2, 19) else "--self-contained")
            cmd += ["--metadata", f"pagetitle={dst.stem}"]
        if edge.dst in TEXT_WRITERS:
            # Images inside the document are written next to the result.
            cmd.append(f"--extract-media={dst.stem}_media")
        if edge.dst == "md":
            cmd.append("--wrap=none")
        if edge.dst == "typ":
            cmd += ["-V", f"papersize={i18n.paper_size()}"]
        if edge.dst == "pdf":
            engine = pdf_engine()
            cmd.append(f"--pdf-engine={engine}")
            if engine in ("xelatex", "lualatex", "pdflatex", "tectonic"):
                paper = "letter" if i18n.paper_size() == "us-letter" else "a4"
                cmd += ["-V", "geometry:margin=2.5cm", "-V", f"papersize={paper}"]
        ctx.run(cmd, cwd=dst.parent, timeout=900)
        return dst
