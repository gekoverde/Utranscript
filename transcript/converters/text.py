"""Plain text and source code, plus Typst documents to PDF."""

from __future__ import annotations

import html
import importlib.util
import os
import re
from pathlib import Path

from .. import i18n, tools
from .base import ConversionError, Converter, Edge

_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)
# A Latin-1 symbol inside a word ("Za¿ó³æ") means the bytes are in another code page (Polish...).
_SYMBOL_IN_WORD = re.compile(r"[^\W\d_][\u00a1-\u00b6\u00b8-\u00bf][^\W\d_]")


def read_text(path: Path) -> str:
    """Read a text file whatever its encoding (UTF-8, UTF-16, Windows-1252...), with "\\n" line ends."""
    text = _decode(path.read_bytes())
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _decode(data: bytes) -> str:
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for encoding in _legacy_encodings():
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    western = _western(data)
    if western is not None:
        return western
    try:
        from charset_normalizer import from_bytes

        for match in from_bytes(data):
            # Without NUL bytes the data cannot be UTF-16/32: those guesses turn text into CJK.
            if b"\x00" in data or not match.encoding.startswith(("utf_16", "utf_32")):
                return str(match)
    except Exception:
        pass
    return data.decode("cp1252", errors="replace")


def _legacy_encodings() -> list[str]:
    """Encodings to trust before guessing: the one the user asked for (TRANSCRIPT_ENCODING), and on
    Windows the system's own code page when it is not Windows-1252 (cp1250 on a Czech PC, cp1251 on a
    Russian one...): old files on a computer are usually in its code page."""
    encodings = [os.environ["TRANSCRIPT_ENCODING"]] if os.environ.get("TRANSCRIPT_ENCODING") else []
    if tools.WINDOWS:
        try:
            import ctypes

            code_page = ctypes.windll.kernel32.GetACP()
            if code_page not in (1252, 65001):  # Windows-1252 is checked below, 65001 is UTF-8
                encodings.append(f"cp{code_page}")
        except Exception:
            pass
    return encodings


def _western(data: bytes) -> str | None:
    """Windows-1252, the usual 8-bit encoding of Western text, when the result looks like it.

    Detectors often pick another code page for short Western text (ñ read as ń). Text in other
    alphabets also decodes as Windows-1252, but then most of its letters are not ASCII.
    """
    if b"\x00" in data:
        return None
    try:
        text = data.decode("cp1252")
    except UnicodeDecodeError:
        return None
    letters = [c for c in text if c.isalpha()]
    if sum(not c.isascii() for c in letters) >= 0.35 * len(letters) > 0 or _SYMBOL_IN_WORD.search(text):
        return None
    return text


def write_text(path: Path, text: str) -> Path:
    """Write UTF-8 text with "\\n" line ends on every system (Windows would write "\\r\\n")."""
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def utf8_copy(src: Path, folder: Path) -> Path:
    """A UTF-8 copy of a text file, for programs that guess other encodings wrong."""
    return write_text(folder / src.name, read_text(src))


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
            write_text(dst, text_to_html(text, src.stem))
        elif edge.dst == "txt":
            write_text(dst, text)
        else:
            fence = "````" if "```" in text else "```"
            write_text(dst, f"{fence}{code_language(src)}\n{text.rstrip()}\n{fence}\n")
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
        write_text(work / "content.txt", read_text(src))
        if edge.src == "code":
            body = f'#set text(size: 8.5pt)\n#raw(read("content.txt"), lang: {typst_string(code_language(src))}, block: true)\n'
        else:
            body = (
                "#set text(size: 11pt)\n"
                '#show raw: set text(font: ("Libertinus Serif", "New Computer Modern", "DejaVu Sans"), size: 11pt)\n'
                '#raw(read("content.txt"), block: true)\n'
            )
        main = work / "main.typ"
        write_text(main, f'#set page(paper: "{i18n.paper_size()}", margin: 2cm)\n' + body)
        return typst_compile(main, dst, work)
