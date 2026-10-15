"""Subtitles with pysubs2: SRT, WebVTT, ASS/SSA, MicroDVD, TTML, SAMI."""

from __future__ import annotations

import re
from pathlib import Path

from .base import ConversionError, Converter, Edge
from .text import read_text

PYSUBS2_FORMATS = {"srt": "srt", "vtt": "vtt", "ass": "ass", "ssa": "ssa", "sub": "microdvd", "ttml": "ttml", "sami": "sami"}
FPS = 23.976  # frame based formats (MicroDVD) need a frame rate; this is the most common one


def subtitle_lines(subs) -> list[str]:
    lines: list[str] = []
    for event in subs:
        if event.is_comment:
            continue
        text = re.sub(r"\s+", " ", event.plaintext).strip()
        if text and (not lines or lines[-1] != text):
            lines.append(text)
    return lines


class SubtitleConverter(Converter):
    name = "pysubs2"

    def edges(self):
        from pysubs2.formats import get_format_class

        supported = []
        for fmt, name in PYSUBS2_FORMATS.items():
            try:  # older pysubs2 releases lack TTML and SAMI
                get_format_class(name)
                supported.append(fmt)
            except Exception:
                pass
        edges = self.matrix(supported, supported)
        edges += [self.edge(fmt, "txt") for fmt in supported]
        return edges

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        import pysubs2

        try:
            subs = pysubs2.SSAFile.from_string(read_text(src), format_=PYSUBS2_FORMATS[edge.src], fps=FPS)
        except Exception as exc:
            raise ConversionError(f"cannot read the subtitles: {exc}") from exc
        if edge.dst == "txt":
            dst.write_text("\n".join(subtitle_lines(subs)) + "\n", encoding="utf-8")
            return dst
        try:
            subs.save(str(dst), format_=PYSUBS2_FORMATS[edge.dst], fps=FPS, encoding="utf-8")
        except Exception as exc:
            raise ConversionError(f"cannot write the subtitles: {exc}") from exc
        return dst
