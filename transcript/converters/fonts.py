"""Fonts with fontTools: TTF, OTF, WOFF and WOFF2."""

from __future__ import annotations

from pathlib import Path

from .base import ConversionError, Converter, Edge

FLAVORS = {"ttf": None, "otf": None, "woff": "woff", "woff2": "woff2"}
# A web font is unwrapped into TTF or OTF depending on the outlines it contains.
OUTLINES = {"ttf": "glyf", "otf": "cff"}
OUTLINE_NAMES = {"glyf": "TrueType", "cff": "CFF (PostScript)"}


def outlines(font) -> str:
    return "cff" if ("CFF " in font or "CFF2" in font) else "glyf"


def _outlines(path: Path) -> str:
    from fontTools.ttLib import TTFont

    with TTFont(str(path), lazy=True) as font:
        return outlines(font)


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
        return edge.dst not in OUTLINES or _outlines(src) == OUTLINES[edge.dst]

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        from fontTools.ttLib import TTFont

        try:
            font = TTFont(str(src))
        except Exception as exc:
            raise ConversionError(f"fontTools: {exc}") from exc
        with font:
            # Checked here too, in case a route reaches this step from another font (woff -> woff2 -> ttf).
            found = outlines(font)
            if edge.dst in OUTLINES and found != OUTLINES[edge.dst]:
                other = next(fmt for fmt, kind in OUTLINES.items() if kind == found)
                raise ConversionError(
                    f"the font has {OUTLINE_NAMES[found]} outlines, so it can become {other.upper()}, not {edge.dst.upper()}"
                )
            try:
                font.flavor = FLAVORS[edge.dst]
                font.save(str(dst))
            except Exception as exc:
                raise ConversionError(f"fontTools: {exc}") from exc
        return dst
