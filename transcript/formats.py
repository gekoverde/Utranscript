"""Catalogue of every format Transcript knows about, and file format detection."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Format:
    id: str
    name: str
    category: str
    extensions: tuple[str, ...]  # lowercase, with the dot; the first one is used for output files

    @property
    def ext(self) -> str:
        return self.extensions[0] if self.extensions else ""


# Order matters: it is the order used in menus.
CATEGORIES = (
    "document",
    "spreadsheet",
    "presentation",
    "ebook",
    "image",
    "audio",
    "video",
    "subtitle",
    "text",
    "data",
    "archive",
    "font",
)

# fmt: off
CODE_EXTENSIONS = (
    ".py", ".pyw", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".tsx", ".java", ".kt", ".kts",
    ".scala", ".groovy", ".gradle", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx",
    ".cs", ".fs", ".vb", ".go", ".rs", ".swift", ".m", ".mm", ".rb", ".php", ".pl", ".pm",
    ".lua", ".r", ".jl", ".dart", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1", ".bat",
    ".cmd", ".sql", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".hs", ".erl",
    ".ex", ".exs", ".clj", ".lisp", ".el", ".ml", ".nim", ".zig", ".vhd", ".vhdl", ".asm",
    ".s", ".pas", ".f90", ".cmake", ".mk", ".tf", ".hcl", ".proto", ".graphql", ".gql",
    ".diff", ".patch", ".ino", ".sol", ".coffee", ".elm", ".purs", ".v", ".sv",
)  # ".ts" is handled specially: it is either TypeScript or an MPEG transport stream.

CODE_FILENAMES = {"dockerfile", "makefile", "gnumakefile", "rakefile", "gemfile", "jenkinsfile", "vagrantfile"}
# fmt: on

# fmt: off
RAW_EXTENSIONS = (
    ".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".orf", ".rw2",
    ".raf", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc", ".mrw", ".rwl", ".iiq", ".mos",
)
# fmt: on


def _f(id: str, name: str, category: str, *extensions: str) -> Format:
    return Format(id, name, category, tuple(extensions))


FORMATS: tuple[Format, ...] = (
    # documents
    _f("pdf", "PDF", "document", ".pdf"),
    _f("docx", "Word", "document", ".docx", ".docm", ".dotx"),
    _f("doc", "Word 97-2003", "document", ".doc", ".dot"),
    _f("odt", "OpenDocument Text", "document", ".odt", ".ott"),
    _f("rtf", "Rich Text Format", "document", ".rtf"),
    _f("md", "Markdown", "document", ".md", ".markdown", ".mdown", ".mkd", ".mkdn"),
    _f("html", "HTML", "document", ".html", ".htm", ".xhtml"),
    _f("tex", "LaTeX", "document", ".tex", ".latex"),
    _f("typ", "Typst", "document", ".typ"),
    _f("rst", "reStructuredText", "document", ".rst"),
    _f("adoc", "AsciiDoc", "document", ".adoc", ".asciidoc"),
    _f("org", "Org mode", "document", ".org"),
    _f("textile", "Textile", "document", ".textile"),
    _f("wiki", "MediaWiki", "document", ".wiki", ".mediawiki"),
    _f("dbk", "DocBook", "document", ".dbk", ".docbook"),
    _f("ipynb", "Jupyter Notebook", "document", ".ipynb"),
    _f("opml", "OPML outline", "document", ".opml"),
    _f("wpd", "WordPerfect", "document", ".wpd"),
    _f("wps", "Microsoft Works", "document", ".wps"),
    _f("pages", "Apple Pages", "document", ".pages"),
    _f("odg", "OpenDocument Drawing", "document", ".odg"),
    _f("vsdx", "Visio", "document", ".vsdx", ".vsd"),
    _f("pub", "Microsoft Publisher", "document", ".pub"),
    # spreadsheets
    _f("xlsx", "Excel", "spreadsheet", ".xlsx", ".xlsm", ".xltx"),
    _f("xls", "Excel 97-2003", "spreadsheet", ".xls", ".xlt"),
    _f("ods", "OpenDocument Spreadsheet", "spreadsheet", ".ods", ".ots"),
    _f("csv", "CSV", "spreadsheet", ".csv"),
    _f("tsv", "TSV", "spreadsheet", ".tsv", ".tab"),
    _f("numbers", "Apple Numbers", "spreadsheet", ".numbers"),
    # presentations
    _f("pptx", "PowerPoint", "presentation", ".pptx", ".ppsx", ".pptm", ".potx"),
    _f("ppt", "PowerPoint 97-2003", "presentation", ".ppt", ".pps", ".pot"),
    _f("odp", "OpenDocument Presentation", "presentation", ".odp", ".otp"),
    _f("key", "Apple Keynote", "presentation", ".key"),
    # ebooks
    _f("epub", "EPUB", "ebook", ".epub"),
    _f("mobi", "Kindle MOBI", "ebook", ".mobi", ".prc"),
    _f("azw3", "Kindle AZW3", "ebook", ".azw3", ".azw"),
    _f("fb2", "FictionBook", "ebook", ".fb2"),
    _f("cbz", "Comic book (CBZ)", "ebook", ".cbz"),
    # images
    _f("png", "PNG", "image", ".png", ".apng"),
    _f("jpg", "JPEG", "image", ".jpg", ".jpeg", ".jpe", ".jfif"),
    _f("webp", "WebP", "image", ".webp"),
    _f("avif", "AVIF", "image", ".avif"),
    _f("heic", "HEIC / HEIF", "image", ".heic", ".heif", ".hif"),
    _f("gif", "GIF", "image", ".gif"),
    _f("bmp", "BMP", "image", ".bmp", ".dib"),
    _f("tiff", "TIFF", "image", ".tiff", ".tif"),
    _f("ico", "Windows icon (ICO)", "image", ".ico"),
    _f("icns", "macOS icon (ICNS)", "image", ".icns"),
    _f("svg", "SVG", "image", ".svg", ".svgz"),
    _f("psd", "Photoshop (PSD)", "image", ".psd"),
    _f("tga", "TGA", "image", ".tga"),
    _f("jp2", "JPEG 2000", "image", ".jp2", ".j2k", ".jpf", ".jpx"),
    _f("ppm", "Netpbm", "image", ".ppm", ".pgm", ".pbm", ".pnm"),
    _f("pcx", "PCX", "image", ".pcx"),
    _f("dds", "DirectDraw Surface", "image", ".dds"),
    _f("qoi", "QOI", "image", ".qoi"),
    _f("emf", "Windows metafile (EMF/WMF)", "image", ".emf", ".wmf"),
    _f("raw", "Camera RAW", "image", *RAW_EXTENSIONS),
    # audio
    _f("mp3", "MP3", "audio", ".mp3"),
    _f("wav", "WAV", "audio", ".wav", ".wave"),
    _f("flac", "FLAC", "audio", ".flac"),
    _f("m4a", "M4A (AAC)", "audio", ".m4a", ".m4b"),
    _f("aac", "AAC", "audio", ".aac"),
    _f("ogg", "Ogg Vorbis", "audio", ".ogg", ".oga"),
    _f("opus", "Opus", "audio", ".opus"),
    _f("wma", "Windows Media Audio", "audio", ".wma"),
    _f("aiff", "AIFF", "audio", ".aiff", ".aif", ".aifc"),
    _f("ac3", "AC-3 (Dolby Digital)", "audio", ".ac3"),
    _f("mka", "Matroska audio", "audio", ".mka"),
    _f("amr", "AMR", "audio", ".amr"),
    _f("ape", "Monkey's Audio", "audio", ".ape"),
    _f("wv", "WavPack", "audio", ".wv"),
    _f("caf", "Core Audio (CAF)", "audio", ".caf"),
    _f("au", "Sun audio", "audio", ".au", ".snd"),
    _f("mp2", "MPEG audio layer II", "audio", ".mp2"),
    _f("dts", "DTS", "audio", ".dts"),
    # video
    _f("mp4", "MP4", "video", ".mp4", ".f4v"),
    _f("mkv", "Matroska (MKV)", "video", ".mkv"),
    _f("webm", "WebM", "video", ".webm"),
    _f("mov", "QuickTime (MOV)", "video", ".mov", ".qt"),
    _f("avi", "AVI", "video", ".avi", ".divx"),
    _f("wmv", "Windows Media Video", "video", ".wmv", ".asf"),
    _f("flv", "Flash video (FLV)", "video", ".flv"),
    _f("mpeg", "MPEG", "video", ".mpg", ".mpeg", ".m1v", ".m2v", ".mpe"),
    _f("m4v", "M4V", "video", ".m4v"),
    _f("ogv", "Ogg video (Theora)", "video", ".ogv"),
    _f("3gp", "3GP", "video", ".3gp", ".3g2"),
    _f("ts", "MPEG transport stream", "video", ".ts", ".mts", ".m2ts"),
    _f("vob", "DVD video (VOB)", "video", ".vob"),
    _f("mxf", "MXF", "video", ".mxf"),
    _f("rm", "RealMedia", "video", ".rm", ".rmvb"),
    # subtitles
    _f("srt", "SubRip (SRT)", "subtitle", ".srt"),
    _f("vtt", "WebVTT", "subtitle", ".vtt"),
    _f("ass", "Advanced SubStation (ASS)", "subtitle", ".ass"),
    _f("ssa", "SubStation Alpha (SSA)", "subtitle", ".ssa"),
    _f("sub", "MicroDVD (SUB)", "subtitle", ".sub"),
    _f("ttml", "TTML / DFXP", "subtitle", ".ttml", ".dfxp"),
    _f("sami", "SAMI", "subtitle", ".smi", ".sami"),
    # text
    _f("txt", "Plain text", "text", ".txt", ".text", ".log"),
    _f("code", "Source code", "text", *CODE_EXTENSIONS),
    # data
    _f("json", "JSON", "data", ".json"),
    _f("jsonl", "JSON Lines", "data", ".jsonl", ".ndjson"),
    _f("yaml", "YAML", "data", ".yaml", ".yml"),
    _f("toml", "TOML", "data", ".toml"),
    _f("xml", "XML", "data", ".xml"),
    _f("plist", "Property list", "data", ".plist"),
    _f("ini", "INI", "data", ".ini"),
    # archives
    _f("zip", "ZIP", "archive", ".zip"),
    _f("7z", "7-Zip", "archive", ".7z"),
    _f("tar", "TAR", "archive", ".tar"),
    _f("tgz", "TAR + gzip", "archive", ".tar.gz", ".tgz"),
    _f("tbz2", "TAR + bzip2", "archive", ".tar.bz2", ".tbz2", ".tbz"),
    _f("txz", "TAR + xz", "archive", ".tar.xz", ".txz"),
    _f("rar", "RAR", "archive", ".rar"),
    _f("iso", "Disk image (ISO)", "archive", ".iso"),
    _f("cab", "Cabinet (CAB)", "archive", ".cab"),
    _f("folder", "Folder", "archive"),
    # fonts
    _f("ttf", "TrueType", "font", ".ttf"),
    _f("otf", "OpenType", "font", ".otf"),
    _f("woff", "WOFF", "font", ".woff"),
    _f("woff2", "WOFF2", "font", ".woff2"),
)

BY_ID: dict[str, Format] = {f.id: f for f in FORMATS}

_BY_EXT: dict[str, str] = {}
for _fmt in FORMATS:
    for _ext in _fmt.extensions:
        _BY_EXT.setdefault(_ext, _fmt.id)
_COMPOUND = sorted((e for e in _BY_EXT if e.count(".") > 1), key=len, reverse=True)


def get(fmt_id: str) -> Format:
    return BY_ID[fmt_id]


def ids_in(category: str) -> list[str]:
    return [f.id for f in FORMATS if f.category == category]


def lookup(name: str) -> str | None:
    """Resolve a user supplied format name or extension (``pdf``, ``.jpeg``, ``tar.gz``)."""
    key = name.strip().lower()
    if key in BY_ID:
        return key
    if not key.startswith("."):
        key = "." + key
    return _BY_EXT.get(key)


def split_name(path: Path) -> tuple[str, str]:
    """Split a file name into (stem, extension), understanding ``.tar.gz`` and friends."""
    name = path.name
    lower = name.lower()
    for ext in _COMPOUND:
        if lower.endswith(ext) and len(name) > len(ext):
            return name[: -len(ext)], name[-len(ext) :]
    if path.suffix and path.stem:
        return path.stem, path.suffix
    return name, ""


def detect(path: Path) -> str | None:
    """Best effort detection of the format of ``path``. Returns a format id or None."""
    if path.is_dir():
        return "folder"
    lower = path.name.lower()
    if lower in CODE_FILENAMES:
        return "code"
    _, ext = split_name(path)
    ext = ext.lower()
    if ext == ".ts":
        return "ts" if _is_mpeg_ts(path) else "code"
    if ext in _BY_EXT:
        return _BY_EXT[ext]
    return sniff(path)


def _read_head(path: Path, size: int = 4096) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(size)
    except OSError:
        return b""


def _is_mpeg_ts(path: Path) -> bool:
    head = _read_head(path, 189)
    return len(head) >= 189 and head[0] == 0x47 and head[188] == 0x47


_MAGIC: tuple[tuple[int, bytes, str], ...] = (
    (0, b"%PDF", "pdf"),
    (0, b"\x89PNG\r\n\x1a\n", "png"),
    (0, b"\xff\xd8\xff", "jpg"),
    (0, b"GIF87a", "gif"),
    (0, b"GIF89a", "gif"),
    (0, b"II*\x00", "tiff"),
    (0, b"MM\x00*", "tiff"),
    (0, b"8BPS", "psd"),
    (0, b"qoif", "qoi"),
    (0, b"DDS ", "dds"),
    (0, b"\x00\x00\x01\x00", "ico"),
    (0, b"icns", "icns"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z"),
    (0, b"Rar!\x1a\x07", "rar"),
    (0, b"MSCF", "cab"),
    (0, b"\x1f\x8b", "tgz"),
    (0, b"BZh", "tbz2"),
    (0, b"\xfd7zXZ\x00", "txz"),
    (257, b"ustar", "tar"),
    (0, b"ID3", "mp3"),
    (0, b"fLaC", "flac"),
    (0, b"OggS", "ogg"),
    (0, b"#!AMR", "amr"),
    (0, b"MAC ", "ape"),
    (0, b"wvpk", "wv"),
    (0, b"caff", "caf"),
    (0, b".snd", "au"),
    (0, b"FLV", "flv"),
    (0, b"\x30\x26\xb2\x75\x8e\x66\xcf\x11", "wmv"),
    (0, b"\x00\x00\x01\xba", "mpeg"),
    (0, b".RMF", "rm"),
    (0, b"wOFF", "woff"),
    (0, b"wOF2", "woff2"),
    (0, b"OTTO", "otf"),
    (0, b"\x00\x01\x00\x00\x00", "ttf"),
    (0, b"{\\rtf", "rtf"),
    (0, b"bplist", "plist"),
    (0, b"\xd7\xcd\xc6\x9a", "emf"),
)

# fmt: off
_FTYP_BRANDS = {
    b"heic": "heic", b"heix": "heic", b"heim": "heic", b"heis": "heic", b"hevc": "heic",
    b"mif1": "heic", b"msf1": "heic", b"avif": "avif", b"avis": "avif", b"M4A ": "m4a",
    b"M4B ": "m4a", b"M4V ": "m4v", b"qt  ": "mov", b"3gp4": "3gp", b"3gp5": "3gp",
    b"3gp6": "3gp", b"3g2a": "3gp", b"crx ": "raw",
}
# fmt: on

_ZIP_MIMETYPES = {
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/vnd.oasis.opendocument.graphics": "odg",
    "application/epub+zip": "epub",
}


def sniff(path: Path) -> str | None:
    """Detect a format from the file content (used when the extension is unknown)."""
    head = _read_head(path)
    if not head:
        return None
    if head.startswith(b"PK\x03\x04"):
        return _sniff_zip(path)
    if head[:4] == b"RIFF" and len(head) >= 12:
        return {b"WAVE": "wav", b"AVI ": "avi", b"WEBP": "webp"}.get(head[8:12])
    if head[4:8] == b"ftyp":
        return _FTYP_BRANDS.get(head[8:12], "mp4")
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm" if b"webm" in head[:64] else "mkv"
    if head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xf3" or head[:2] == b"\xff\xf2":
        return "mp3"
    for offset, magic, fmt in _MAGIC:
        if head[offset : offset + len(magic)] == magic:
            return fmt
    return _sniff_text(head)


def _sniff_zip(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "mimetype" in names:
                mime = zf.read("mimetype").decode("ascii", "ignore").strip()
                if mime in _ZIP_MIMETYPES:
                    return _ZIP_MIMETYPES[mime]
            if "[Content_Types].xml" in names:
                if any(n.startswith("word/") for n in names):
                    return "docx"
                if any(n.startswith("xl/") for n in names):
                    return "xlsx"
                if any(n.startswith("ppt/") for n in names):
                    return "pptx"
    except (zipfile.BadZipFile, OSError):
        pass
    return "zip"


def _sniff_text(head: bytes) -> str | None:
    if b"\x00" in head:
        return None
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        # Legacy 8-bit text (Windows-1252, Latin-1...) still counts as text if it has no control junk.
        text = head.decode("latin-1")
        if sum(ch < 32 and ch not in (9, 10, 13) for ch in head) > len(head) // 100:
            return None
    stripped = text.lstrip("﻿ \t\r\n").lower()
    if stripped.startswith("<?xml") or stripped.startswith("<svg"):
        return "svg" if "<svg" in stripped[:2048] else "xml"
    if stripped.startswith("<!doctype html") or stripped.startswith("<html"):
        return "html"
    if stripped.startswith("{\\rtf"):
        return "rtf"
    if stripped[:1] in ("{", "["):
        return "json"
    if stripped.startswith("webvtt"):
        return "vtt"
    return "txt"
