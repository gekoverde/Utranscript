"""Subtitles with pysubs2: SRT, WebVTT, ASS/SSA, MicroDVD, TTML, SAMI."""

from __future__ import annotations

import re
from pathlib import Path

from .base import ConversionError, Converter, Edge
from .text import read_text

PYSUBS2_FORMATS = {"srt": "srt", "vtt": "vtt", "ass": "ass", "ssa": "ssa", "sub": "microdvd", "ttml": "ttml", "sami": "sami"}
FPS = 23.976  # frame based formats (MicroDVD) need a frame rate; this is the most common one
MICRODVD_FPS = re.compile(r"\s*\{[01]\}\{[01]\}\s*(\d+(?:\.\d+)?)\s*(?:\n|$)")
MPEG_PS = b"\x00\x00\x01\xba"  # a binary VobSub .sub starts with an MPEG program stream pack header


def subtitle_lines(subs) -> list[str]:
    lines: list[str] = []
    for event in subs:
        if event.is_comment:
            continue
        text = re.sub(r"\s+", " ", event.plaintext).strip()
        if text and (not lines or lines[-1] != text):
            lines.append(text)
    return lines


def writable(name: str) -> bool:
    """Whether pysubs2 can write the format (SAMI, for one, can only be read)."""
    from pysubs2.formats import FormatBase, get_format_class

    # to_file is a classmethod: the bound methods always differ, the underlying functions do not.
    return get_format_class(name).to_file.__func__ is not FormatBase.to_file.__func__


def read_subtitles(src: Path, fmt: str):
    import pysubs2
    from pysubs2.exceptions import UnknownFPSError

    with open(src, "rb") as fh:
        if fmt == "microdvd" and fh.read(4) == MPEG_PS:
            raise ConversionError("this .sub file is a VobSub (DVD picture-based subtitles), which is not supported")
    text = read_text(src)
    fps = None
    if fmt == "microdvd":
        # MicroDVD files usually declare their frame rate in a first "{1}{1}25.000" line ("{0}{0}"
        # in older files). Read it here: pysubs2 only understands some forms, depending on its version.
        match = MICRODVD_FPS.match(text)
        if match:
            fps = float(match.group(1))
            text = text[match.end() :]
    try:
        try:
            subs = pysubs2.SSAFile.from_string(text, format_=fmt, fps=fps)
        except UnknownFPSError:
            subs = pysubs2.SSAFile.from_string(text, format_=fmt, fps=FPS)
    except Exception as exc:
        raise ConversionError(f"cannot read the subtitles: {exc}") from exc
    if all(event.is_comment for event in subs):
        raise ConversionError("no subtitles found in the file")
    return subs


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
        edges = self.matrix(supported, [fmt for fmt in supported if writable(PYSUBS2_FORMATS[fmt])])
        edges += [self.edge(fmt, "txt") for fmt in supported]
        return edges

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        subs = read_subtitles(src, PYSUBS2_FORMATS[edge.src])
        if edge.dst == "txt":
            dst.write_text("\n".join(subtitle_lines(subs)) + "\n", encoding="utf-8")
            return dst
        try:
            subs.save(str(dst), format_=PYSUBS2_FORMATS[edge.dst], fps=FPS, encoding="utf-8")
        except Exception as exc:
            raise ConversionError(f"cannot write the subtitles: {exc}") from exc
        return dst
