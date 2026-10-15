"""Plain text and source code, plus Typst documents to PDF."""

from __future__ import annotations

import html
import importlib.util
from pathlib import Path

from .. import i18n
from .base import ConversionError, Converter, Edge


def read_text(path: Path) -> str:
    """Read a text file whatever its encoding (UTF-8, UTF-16, Windows-1252...)."""
    data = path.read_bytes()
    for bom, encoding in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if data.startswith(bom):
            return data.decode(encoding)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    return data.decode("cp1252", errors="replace")


def typst_compile(main: Path, dst: Path, root: Path) -> Path:
    import typst

    try:
        typst.compile(str(main), output=str(dst), root=str(root))
    except Exception as exc:
        raise ConversionError(f"Typst: {str(exc).strip()[:2000]}") from exc
    return dst


def typst_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def text_to_html(text: str, title: str) -> str:
    paragraphs = []
    for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        if block.strip():
            lines = [html.escape(line) for line in block.strip("\n").split("\n")]
            paragraphs.append("<p>" + "<br>\n".join(lines) + "</p>")
    return (
        '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(title)}</title>\n</head>\n<body>\n" + "\n".join(paragraphs) + "\n</body>\n</html>\n"
    )


def code_language(path: Path) -> str:
    """Language tag for Markdown fences and Typst raw blocks."""
    name = path.name.lower()
    if name in ("dockerfile", "makefile"):
        return name
    return path.suffix.lower().lstrip(".")


class TextConverter(Converter):
    """Plain text and source code to HTML and Markdown."""

    name = "Transcript"

    def edges(self):
        return [self.edge("txt", "html"), self.edge("code", "txt"), self.edge("code", "md")]

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        text = read_text(src)
        if edge.dst == "html":
            dst.write_text(text_to_html(text, src.stem), encoding="utf-8")
        elif edge.dst == "txt":
            dst.write_text(text, encoding="utf-8")
        else:
            fence = "````" if "```" in text else "```"
            dst.write_text(f"{fence}{code_language(src)}\n{text.rstrip()}\n{fence}\n", encoding="utf-8")
        return dst


class HighlightConverter(Converter):
    """Source code to syntax highlighted HTML and RTF."""

    name = "Pygments"

    def available(self) -> bool:
        return importlib.util.find_spec("pygments") is not None

    def edges(self):
        return [self.edge("code", "html"), self.edge("code", "rtf")]

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter, RtfFormatter
        from pygments.lexers import TextLexer, get_lexer_for_filename, guess_lexer
        from pygments.util import ClassNotFound

        text = read_text(src)
        try:
            lexer = get_lexer_for_filename(src.name, text)
        except ClassNotFound:
            try:
                lexer = guess_lexer(text)
            except ClassNotFound:
                lexer = TextLexer()
        if edge.dst == "html":
            formatter = HtmlFormatter(full=True, linenos="table", title=src.name, encoding="utf-8")
        else:
            formatter = RtfFormatter(fontface="Consolas", encoding="utf-8")
        dst.write_bytes(highlight(text, lexer, formatter))
        return dst


class TypstConverter(Converter):
    """PDF typesetting with Typst: Typst documents, plain text and highlighted code."""

    name = "Typst"
    hint = "pip install typst"

    def available(self) -> bool:
        return importlib.util.find_spec("typst") is not None

    def details(self) -> str:
        import typst

        return f"typst-py {getattr(typst, '__version__', '')}".strip()

    def edges(self):
        # Slightly cheaper than the alternatives: Typst produces the nicest PDFs.
        return [self.edge("typ", "pdf", cost=0.9), self.edge("txt", "pdf"), self.edge("code", "pdf")]

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        if edge.src == "typ":
            return typst_compile(src, dst, src.parent)
        work = ctx.scratch("typst")
        (work / "content.txt").write_text(read_text(src), encoding="utf-8")
        if edge.src == "code":
            body = f'#set text(size: 8.5pt)\n#raw(read("content.txt"), lang: {typst_string(code_language(src))}, block: true)\n'
        else:
            body = (
                "#set text(size: 11pt)\n"
                '#show raw: set text(font: ("Libertinus Serif", "New Computer Modern", "DejaVu Sans"), size: 11pt)\n'
                '#raw(read("content.txt"), block: true)\n'
            )
        main = work / "main.typ"
        main.write_text(f'#set page(paper: "{i18n.paper_size()}", margin: 2cm)\n' + body, encoding="utf-8")
        return typst_compile(main, dst, work)
