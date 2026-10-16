"""Base classes shared by every converter."""

from __future__ import annotations

import itertools
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..tools import ConversionError

if TYPE_CHECKING:
    from ..engine import Context

__all__ = ["Converter", "Edge", "ConversionError", "Context"]


@dataclass(frozen=True)
class Edge:
    """One direct conversion a converter can perform."""

    src: str
    dst: str
    converter: Converter = field(compare=False, repr=False)
    cost: float = 1.0
    # A terminal edge can only be the last step of a route: its output is lossy or
    # may be a folder of several files (PDF pages, an extracted archive...).
    terminal: bool = False
    # Only usable on the original file (e.g. an animated GIF to video, which makes no
    # sense for a GIF that was itself converted from a still picture).
    first_only: bool = False


class Converter:
    """A conversion engine. Subclasses declare what they can do through ``edges``."""

    name = "?"
    # Shown by ``transcript --doctor`` when the engine is not available.
    hint = ""

    def available(self) -> bool:
        return True

    def details(self) -> str:
        """Short description for ``transcript --doctor`` (path, version...)."""
        return ""

    def edges(self) -> Iterable[Edge]:
        return ()

    def accepts(self, src: Path, edge: Edge, ctx: Context) -> bool:
        """Check against the actual input file, for the steps of a route still in its category."""
        return True

    def convert(self, src: Path, dst: Path, edge: Edge, ctx: Context) -> Path:
        """Convert ``src`` into ``dst`` and return the produced path.

        The returned path is normally ``dst``; converters producing several files return a
        folder instead (``dst`` without its extension).
        """
        raise NotImplementedError

    # helpers -------------------------------------------------------------------------------

    def edge(self, src: str, dst: str, cost: float = 1.0, terminal: bool = False, first_only: bool = False) -> Edge:
        return Edge(src, dst, self, cost, terminal, first_only)

    def matrix(
        self,
        sources: Iterable[str],
        targets: Iterable[str],
        cost: float | Callable[[str, str], float] = 1.0,
        terminal: bool = False,
    ) -> list[Edge]:
        targets = list(targets)
        out = []
        for src, dst in itertools.product(sources, targets):
            if src != dst:
                c = cost(src, dst) if callable(cost) else cost
                out.append(Edge(src, dst, self, c, terminal))
        return out


def move_into(produced: Path, dst: Path) -> Path:
    """Move a file produced by an external tool to the path the engine expects."""
    if not produced.exists():
        raise ConversionError(f"the expected output was not produced ({produced.name})")
    if produced != dst:
        shutil.move(str(produced), str(dst))
    return dst
