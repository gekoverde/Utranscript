"""Registry of every conversion engine."""

from __future__ import annotations

from functools import cache

from .archives import ArchiveConverter
from .base import Converter, Edge
from .data import DataConverter
from .documents import PandocConverter
from .ebooks import CalibreConverter
from .fonts import FontConverter
from .images import PillowConverter, RawConverter, SvgConverter
from .media import FFmpegConverter
from .ocr import OcrConverter
from .office import LibreOfficeConverter
from .pdf import PdfConverter
from .speech import SpeechConverter
from .subtitles import SubtitleConverter
from .text import HighlightConverter, TextConverter, TypstConverter


@cache
def all_converters() -> tuple[Converter, ...]:
    return (
        PandocConverter(),
        LibreOfficeConverter(),
        TypstConverter(),
        TextConverter(),
        HighlightConverter(),
        PdfConverter(),
        PillowConverter(),
        SvgConverter(),
        RawConverter(),
        FFmpegConverter(),
        SpeechConverter(),
        OcrConverter(),
        SubtitleConverter(),
        DataConverter(),
        ArchiveConverter(),
        FontConverter(),
        CalibreConverter(),
    )


@cache
def converter_edges(converter: Converter) -> tuple[Edge, ...]:
    """The edges of an available converter; a broken engine simply contributes nothing."""
    try:
        if not converter.available():
            return ()
        return tuple(converter.edges())
    except Exception:
        return ()


@cache
def all_edges() -> tuple[Edge, ...]:
    from concurrent.futures import ThreadPoolExecutor

    # Engines are probed in parallel: several of them start an external program.
    with ThreadPoolExecutor(max_workers=8) as pool:
        groups = list(pool.map(converter_edges, all_converters()))
    return tuple(edge for group in groups for edge in group)
