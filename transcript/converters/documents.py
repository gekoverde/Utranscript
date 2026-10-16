"""Documents with pandoc: Markdown, HTML, Word, OpenDocument, EPUB, LaTeX, Typst..."""

from __future__ import annotations

import contextlib
import os
import re
from functools import cache
from pathlib import Path

from .. import i18n, tools
from .base import ConversionError, Converter, Edge
from .text import read_text, utf8_copy

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

# Formats pandoc reads as text, always as UTF-8.
TEXT_READERS = {"md", "html", "tex", "typ", "rst", "adoc", "org", "textile", "wiki", "dbk", "opml", "fb2", "csv", "tsv"}
STANDALONE = {"html", "tex", "rtf", "typ", "dbk", "opml", "fb2", "epub"}
TEXT_WRITERS = {"md", "rst", "adoc", "org", "textile", "wiki", "tex", "typ", "dbk", "ipynb"}
OFFICE = {"docx", "odt", "rtf"}
PDF_ENGINES = ("xelatex", "lualatex", "tectonic", "pdflatex", "typst", "weasyprint", "wkhtmltopdf")
# Lua filter that keeps files outside the document's folder out of the result.
SAFE_FILTER = Path(__file__).with_name("pandoc_safe.lua")


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
        source = _pandoc_source(src, edge.src, ctx) if edge.src in TEXT_READERS else src
        cmd = [tools.pandoc(), str(source.resolve()), "-f", reader, "-t", writer, "-o", dst.name]
        cmd.append(f"--lua-filter={SAFE_FILTER}")
        # Images are looked up next to the original, also when pandoc reads a converted copy.
        root = src.resolve().parent
        resources = _resource_folder(root, ctx)
        if resources:
            cmd.append(f"--resource-path={resources}{os.pathsep}.")
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
        try:
            ctx.run(cmd, cwd=dst.parent, timeout=900)
        finally:
            if resources and resources != root:
                _remove_link(resources)
        return dst


# Directives that make pandoc read another file while it parses, before any filter can step in.
INCLUDES = {
    "rst": re.compile(r"^\s*\.\.\s+(?:include|literalinclude)::\s*(\S.*?)\s*$|^\s+:file:\s*(\S.*?)\s*$", re.M),
    "org": re.compile(r"^\s*#\+(?:include|setupfile):\s*\"?([^\"\s]+)", re.M | re.I),
    "tex": re.compile(r"\\(?:input|include|subfile|import|subimport)\s*\{([^}]*)\}"),
    "adoc": re.compile(r"^\s*include::([^\[\n]+)\[", re.M),
    "typ": re.compile(r"#include\s+\"([^\"]+)\""),
}


def _pandoc_source(src: Path, fmt: str, ctx) -> Path:
    """The file pandoc reads: ``src``, or a UTF-8 copy of it.

    pandoc reads other encodings as Latin-1 ("€" becomes an invisible control character). A file
    with include directives is passed as it is, so that the files next to it are still found.
    """
    data = src.read_bytes()
    includes = _check_includes(src, fmt, read_text(src))
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        if not includes:
            return utf8_copy(src, ctx.scratch("pandoc"))
    return src


def _check_includes(src: Path, fmt: str, text: str) -> bool:
    """Refuse a document that includes files from outside its folder (an absolute path, a URL,
    "../"...): a downloaded document must not copy the user's private files into the result.
    Returns whether it includes any file."""
    pattern = INCLUDES.get(fmt)
    if pattern is None:
        return False
    root = src.resolve().parent
    found = False
    for match in pattern.finditer(text):
        target = next(group for group in match.groups() if group).strip().strip("\"'")
        found = True
        if _outside(target, root):
            raise ConversionError(f"the document includes '{target}', which is outside its folder: refused for safety")
    return found


def _outside(target: str, root: Path) -> bool:
    if re.match(r"[a-zA-Z][\w+.-]*:", target) or target.startswith(("/", "\\", "~")):
        return True  # URL, "file:", drive letter, absolute or home path
    try:
        return not (root / target).resolve().is_relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return True


def _remove_link(link: Path) -> None:
    """Remove a symlink or junction, never what it points to."""
    for remove in (os.unlink, os.rmdir):  # a Windows junction needs rmdir
        with contextlib.suppress(OSError):
            remove(link)
            return


def _resource_folder(folder: Path, ctx) -> Path | None:
    """``folder`` for --resource-path, a list split on os.pathsep (":" or ";").

    A folder whose name contains the separator is reached through a link with a plain name.
    """
    if os.pathsep not in str(folder):
        return folder
    link = ctx.scratch("pandoc") / "source"
    if os.pathsep in str(link):
        return None
    try:
        if tools.WINDOWS:
            import _winapi

            _winapi.CreateJunction(str(folder), str(link))  # unlike symlinks, needs no privileges
        else:
            link.symlink_to(folder, target_is_directory=True)
    except OSError:
        return None
    return link
