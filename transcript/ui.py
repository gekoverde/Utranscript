"""Terminal user interface: the "to" menu and progress display."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.text import Text

from . import formats
from .converters.base import Edge
from .engine import Reporter
from .i18n import t
from .planner import Route

# No emoji codes: ':a:' in an FFmpeg message or ':smile:' in a file name must be printed as is.
console = Console(highlight=False, emoji=False)
err_console = Console(stderr=True, highlight=False, emoji=False)


def format_label(fmt_id: str) -> str:
    fmt = formats.get(fmt_id)
    return t(f"fmt.{fmt_id}", fmt.name)


def human_size(path: Path) -> str:
    try:
        size = path.stat().st_size if path.is_file() else sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def describe_route(route: Route) -> str:
    if not route.via:
        return ""
    return t("menu.via", path=" → ".join(formats.get(f).id.upper() for f in route.via))


def menu_rows(routes: dict[str, Route]) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Group the targets by category, in catalogue order: [(category, [(id, label, via)])].

    The category of the source file comes first (images first for a photo, video for a movie...).
    """
    order = {f.id: i for i, f in enumerate(formats.FORMATS)}
    categories = list(formats.CATEGORIES)
    if routes:
        own = formats.get(next(iter(routes.values())).source).category
        categories.sort(key=lambda c: c != own)
    groups: list[tuple[str, list[tuple[str, str, str]]]] = []
    for category in categories:
        ids = sorted((f for f in routes if formats.get(f).category == category), key=order.get)
        if ids:
            groups.append((category, [(f, format_label(f), describe_route(routes[f])) for f in ids]))
    return groups


class MenuTitle(str):
    """A menu row as shown, whose type-to-filter search only sees part of it.

    questionary filters on ``title.lower()``: the route ("via TXT") and the category headings are
    left out of it, so typing "txt" picks Plain text and not "PDF  via TXT".
    """

    searchable: str

    def __new__(cls, text: str, searchable: str):
        title = super().__new__(cls, text)
        title.searchable = searchable
        return title

    def lower(self) -> str:
        return self.searchable.lower()


def choose_target(routes: dict[str, Route]) -> str | None:
    """Show the interactive "to" menu and return the chosen format id (None if cancelled)."""
    import questionary
    from questionary import Choice, Separator, Style

    groups = menu_rows(routes)
    width = max(len(label) for _, rows in groups for _, label, _ in rows)
    choices: list = []
    for category, rows in groups:
        heading = Separator(f"── {t('cat.' + category)} ──")
        heading.title = MenuTitle(heading.title, "")  # headings never match what is typed
        choices.append(heading)
        for fmt_id, label, via in rows:
            ext = formats.get(fmt_id).ext or "/"
            searchable = f"{label:<{width}}  {ext}"
            choices.append(Choice(title=MenuTitle(f"{searchable:<{width + 11}}{via}", searchable), value=fmt_id))
    style = Style(
        [
            ("qmark", "fg:#61afef bold"),
            ("question", "bold"),
            ("pointer", "fg:#61afef bold"),
            ("highlighted", "fg:#61afef bold"),
            ("separator", "fg:#7f848e"),
            ("instruction", "fg:#7f848e"),
        ]
    )
    while True:
        answer = questionary.select(
            t("menu.title"),
            choices=choices,
            qmark="",
            pointer="❯",
            instruction=t("menu.instruction"),
            use_search_filter=True,
            use_jk_keys=False,
            use_shortcuts=False,
            style=style,
        ).ask(kbi_msg="")
        # After typing, the cursor can rest on a category heading, and Enter returns its title.
        if answer is None or answer in routes:
            return answer


class RichReporter(Reporter):
    """Shows one progress line per conversion step."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._progress: Progress | None = None
        self._task = None

    def step(self, edge: Edge) -> None:
        self.finish_step()
        description = t(
            "convert.step",
            src=formats.get(edge.src).id.upper(),
            dst=formats.get(edge.dst).id.upper(),
            engine=edge.converter.name,
        )
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        self._progress.start()
        self._task = self._progress.add_task(description, total=None)

    def progress(self, done: float, total: float | None = None) -> None:
        if self._progress is not None and self._task is not None:
            if total:
                self._progress.update(self._task, total=total, completed=min(done, total))

    def log(self, message: str) -> None:
        target = self._progress.console if self._progress else console
        target.print(Text(message, style="dim"), soft_wrap=True)

    def finish_step(self, ok: bool = True) -> None:
        if self._progress is not None:
            task = self._progress.tasks[0]
            if ok:
                self._progress.update(self._task, total=task.total or 1, completed=task.total or 1)
            self._progress.stop()
            self._progress = None
            self._task = None


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
