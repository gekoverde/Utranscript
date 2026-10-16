"""Finding the best chain of conversions between two formats.

Every converter contributes direct edges (``docx -> pdf``, ``mp4 -> mp3``...). The planner
runs a cheapest-path search over that graph so that formats without a direct converter
can still be reached through intermediate formats (``md -> typ -> pdf``).
"""

from __future__ import annotations

import heapq
import itertools
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from . import formats
from .converters.base import Edge

MAX_STEPS = 4
HOP_PENALTY = 0.25  # prefer fewer steps when costs are similar
# Each step that changes the kind of file (video -> text -> document...) loses meaning.
# Two changes still allow "video -> transcript -> Word", but not "video -> transcript ->
# PDF -> PNG", which would be an image of the transcript rather than of the video.
MAX_CATEGORY_CHANGES = 2


@dataclass(frozen=True)
class Route:
    edges: tuple[Edge, ...]
    cost: float

    @property
    def source(self) -> str:
        return self.edges[0].src

    @property
    def target(self) -> str:
        return self.edges[-1].dst

    @property
    def via(self) -> list[str]:
        """Intermediate formats, empty for direct conversions."""
        return [e.dst for e in self.edges[:-1]]


def _category(fmt: str) -> str:
    return formats.BY_ID[fmt].category if fmt in formats.BY_ID else fmt


def plan(
    source: str,
    edges: Iterable[Edge],
    first_step_ok: Callable[[Edge], bool] | None = None,
    max_steps: int = MAX_STEPS,
    check_same_category: bool = False,
) -> dict[str, Route]:
    """Return the cheapest route from ``source`` to every reachable format.

    ``first_step_ok`` checks the first step against the actual input file. With ``check_same_category``
    it also checks the later steps while the route is still in the category of the source: what it
    looks at (the audio and video streams, the font outlines) survives those steps, so
    ``mp4 -> m4v -> mp3`` is no way around a video without sound.
    """
    by_src: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        by_src[edge.src].append(edge)

    best: dict[str, Route] = {}
    expanded: set[tuple[str, int]] = set()
    counter = itertools.count()
    heap: list[tuple[float, int, str, int, tuple[Edge, ...]]] = [(0.0, next(counter), source, 0, ())]

    while heap:
        cost, _, node, changes, path = heapq.heappop(heap)
        if (node, changes) in expanded:
            continue
        expanded.add((node, changes))
        if len(path) >= max_steps:
            continue
        for edge in by_src.get(node, ()):
            if edge.dst == source or any(e.src == edge.dst for e in path):
                continue
            if edge.first_only and path:
                continue
            new_changes = changes + (_category(edge.src) != _category(edge.dst))
            if new_changes > MAX_CATEGORY_CHANGES:
                continue
            checked = not path or (check_same_category and changes == 0)
            if checked and first_step_ok is not None and not first_step_ok(edge):
                continue
            new_cost = cost + edge.cost + HOP_PENALTY
            new_path = path + (edge,)
            known = best.get(edge.dst)
            if known is None or new_cost < known.cost:
                best[edge.dst] = Route(new_path, new_cost)
            if not edge.terminal:
                heapq.heappush(heap, (new_cost, next(counter), edge.dst, new_changes, new_path))
    return best
