"""Fonts with fontTools: TTF, OTF, WOFF and WOFF2."""

from __future__ import annotations

from pathlib import Path

from .base import ConversionError, Converter, Edge

FLAVORS = {"ttf": None, "otf": None, "woff": "woff", "woff2": "woff2"}


def _outlines(path: Path) -> str:
    from fontTools.ttLib import TTFont

    with TTFont(str(path), lazy=True) as font:
        return "cff" if ("CFF " in font or "CFF2" in font) else "glyf"


class FontConverter(Converter):
    name = "fontTools"

    def edges(self):
        return [
            self.edge("ttf", "woff"),
            self.edge("ttf", "woff2"),
            self.edge("otf", "woff"),
            self.edge("otf", "woff2"),
            self.edge("woff", "woff2"),
            self.edge("woff2", "woff"),
            self.edge("woff", "ttf"),
            self.edge("woff", "otf"),
            self.edge("woff2", "ttf"),
            self.edge("woff2", "otf"),
        ]

    def accepts(self, src: Path, edge: Edge, ctx) -> bool:
        # A web font is unwrapped into TTF or OTF depending on the outlines it contains.
        if edge.dst == "ttf":
            return _outlines(src) == "glyf"
        if edge.dst == "otf":
            return _outlines(src) == "cff"
        return True

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        from fontTools.ttLib import TTFont

        try:
            with TTFont(str(src)) as font:
                font.flavor = FLAVORS[edge.dst]
                font.save(str(dst))
        except Exception as exc:
            raise ConversionError(f"fontTools: {exc}") from exc
        return dst
