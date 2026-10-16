"""Command line entry point: ``transcript <file>``."""

from __future__ import annotations

import argparse
import glob
import os
import signal
import sys
import traceback
from pathlib import Path

from rich.markup import escape
from rich.table import Table

from . import __version__, formats
from .converters import all_converters, all_edges, converter_edges
from .engine import Context, Options, Workspace, execute, first_step_ok, remove_tree
from .i18n import t
from .planner import Route, plan
from .tools import ConversionError
from .ui import RichReporter, choose_target, console, err_console, format_label, human_size, is_interactive, menu_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="transcript", description=t("help.description"))
    parser.add_argument("files", nargs="*", type=Path, metavar="FILE", help=t("help.files"))
    parser.add_argument("-t", "--to", metavar="FORMAT", help=t("help.to"))
    parser.add_argument("-f", "--from", dest="source", metavar="FORMAT", help=t("help.from"))
    parser.add_argument("-o", "--output", type=Path, metavar="DIR", help=t("help.output"))
    parser.add_argument("--overwrite", action="store_true", help=t("help.overwrite"))
    parser.add_argument("-l", "--list", action="store_true", help=t("help.list"))
    parser.add_argument("--formats", action="store_true", help=t("help.formats"))
    parser.add_argument("--doctor", action="store_true", help=t("help.doctor"))
    parser.add_argument("--dpi", type=int, default=150, help=t("help.dpi"))
    parser.add_argument("--lang", metavar="CODE", help=t("help.lang"))
    parser.add_argument("--model", metavar="NAME", help=t("help.model"))
    parser.add_argument("-v", "--verbose", action="store_true", help=t("help.verbose"))
    parser.add_argument("-V", "--version", action="version", version=f"transcript {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    _prepare_terminal()
    args = build_parser().parse_args(argv)
    try:
        if args.doctor:
            return doctor()
        if args.formats:
            return list_formats()
        if not args.files:
            build_parser().print_help()
            return 0
        return run(args)
    except KeyboardInterrupt:
        err_console.print(t("cancelled"))
        return 130


def _prepare_terminal() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    def terminate(signum, _frame):
        raise SystemExit(128 + signum)  # unwinds the stack so the temporary folder is removed

    # SIGHUP: the terminal was closed or the SSH connection dropped. SIGBREAK: Ctrl+Break on Windows.
    names = ("SIGTERM", "SIGHUP", "SIGQUIT", "SIGBREAK")
    try:
        for signum in (getattr(signal, name) for name in names if hasattr(signal, name)):
            if signal.getsignal(signum) is not signal.SIG_IGN:  # ignored on purpose ('nohup'): leave it so
                signal.signal(signum, terminate)
    except ValueError:  # not running in the main thread
        pass


def error(message: str) -> None:
    err_console.print(f"[bold red]✘[/bold red] {escape(message)}", highlight=False, soft_wrap=True)


def note(message: str) -> None:
    err_console.print(f"[yellow]![/yellow] {escape(message)}", highlight=False, soft_wrap=True)


def clean_path(argument: Path | str) -> Path:
    """Drop the quotes a Windows shell can leave around a path (``-o "C:\\Out Dir\\"`` arrives as ``C:\\Out Dir"``)."""
    return Path(str(argument).strip().strip('"').strip("'")).expanduser()


def expand(arguments: list[Path]) -> list[Path]:
    """Clean up the paths and expand wildcards (Windows shells do not expand ``*.png``)."""
    paths = []
    for argument in arguments:
        path = clean_path(argument)
        if not path.exists() and any(ch in str(path) for ch in "*?["):
            matches = sorted(glob.glob(_pattern(path)))
            if matches:
                paths += [Path(m) for m in matches]
                continue
        paths.append(path)
    return paths


def _pattern(path: Path) -> str:
    """The glob pattern for ``path``: an existing folder is taken literally, even with '[' in its name."""
    parent = path.parent
    if parent != Path(".") and parent.is_dir():
        return os.path.join(glob.escape(str(parent)), path.name)
    return str(path)  # wildcards in the folder part too


def absolute(path: Path) -> Path:
    """The absolute path, keeping a symbolic link's own name and folder (the result goes next to it)."""
    if path.name in ("", ".."):  # '.', '..', a drive: only resolving gives the folder a name
        return path.resolve()
    return path.parent.resolve() / path.name


def run(args: argparse.Namespace) -> int:
    target = formats.lookup(args.to) if args.to else None
    if args.to and target is None:
        error(t("target.unknown", name=args.to))
        return 2
    output = clean_path(args.output) if args.output else None
    jobs: list[tuple[Path, str]] = []
    for path in expand(args.files):
        if path.exists():
            path = absolute(path)
        else:
            error(t("file.not_found", path=path))
            return 2
        if args.source:
            fmt = formats.lookup(args.source)
            if fmt is None:
                error(t("file.unknown_from", name=args.source))
                return 2
        else:
            fmt = formats.detect(path)
            if fmt is None:
                error(t("file.unknown_format", path=path))
                return 2
        if fmt == target and not args.list:
            note(t("file.already", name=path.name, fmt=format_label(fmt)))
            continue
        jobs.append((path, fmt))
    if not jobs:  # every file is already in the target format
        return 0

    options = Options(dpi=args.dpi, lang=args.lang, model=args.model, verbose=args.verbose)
    reporter = RichReporter(args.verbose)
    edges = all_edges()

    space = Workspace()
    with space as workspace:
        if args.verbose:
            reporter.log(t("workspace.created", path=workspace))
        probe_ctx = Context(workspace, options, reporter)
        all_routes: list[dict[str, Route]] = []
        for path, fmt in jobs:
            routes = plan(fmt, edges, first_step_ok(path, probe_ctx), check_same_category=True)
            if not routes:
                # Converters exist, but none accepts this file: it is not what its name says.
                damaged = bool(plan(fmt, edges))
                error(t("file.damaged" if damaged else "file.no_routes", name=path.name, fmt=format_label(fmt)))
                return 1
            all_routes.append(routes)
            console.print(
                f"[bold]{escape(path.name)}[/bold]  [dim]·  {format_label(fmt)}  ·  {human_size(path)}[/dim]",
                highlight=False,
                soft_wrap=True,
            )

        common = set(all_routes[0]).intersection(*all_routes[1:])
        if not common:
            error(t("batch.no_common"))
            return 1
        menu_routes = {k: v for k, v in all_routes[0].items() if k in common}

        if args.list:
            print_targets(menu_routes)
            return 0

        if target is None:
            if not is_interactive():
                error(t("target.noninteractive", targets=targets_line(menu_routes)))
                return 2
            target = choose_target(menu_routes)
            if target not in menu_routes:  # cancelled
                err_console.print(t("cancelled"))
                return 130
        elif target not in common:
            src = ", ".join(sorted({format_label(f) for _, f in jobs}))
            error(t("target.unavailable", src=src, dst=format_label(target), targets=targets_line(menu_routes)))
            return 2

        failures = 0
        for index, ((path, _), routes) in enumerate(zip(jobs, all_routes, strict=True), 1):
            out_dir = output or path.parent
            job_dir = workspace / f"job{index}"
            job_dir.mkdir()
            ctx = Context(job_dir, options, reporter)
            try:
                result = execute(routes[target], path, out_dir, ctx, overwrite=args.overwrite)
                console.print(
                    f"[bold green]✔[/bold green] {escape(t('convert.done', path=result.resolve()))}",
                    highlight=False,
                    soft_wrap=True,
                )
            except ConversionError as exc:
                failures += 1
                error(t("convert.failed", error=exc))
            except Exception as exc:  # a bug or an unexpected library error: keep going with the rest
                failures += 1
                error(t("convert.failed", error=f"{type(exc).__name__}: {exc}"))
                if args.verbose:
                    err_console.print(traceback.format_exc(), highlight=False, markup=False)
            finally:
                remove_tree(job_dir)

    if args.verbose and space.removed:
        reporter.log(t("workspace.removed", path=workspace))
    if failures and len(jobs) > 1:
        error(t("convert.summary_fail", count=failures))
    return 1 if failures else 0


def targets_line(routes: dict[str, Route]) -> str:
    return ", ".join(fmt for _, rows in menu_rows(routes) for fmt, _, _ in rows)


def print_targets(routes: dict[str, Route]) -> None:
    for category, rows in menu_rows(routes):
        console.print(f"[bold]{t('cat.' + category)}[/bold]")
        for fmt_id, label, via in rows:
            console.print(f"  {fmt_id:<8} {label:<28} [dim]{via}[/dim]", highlight=False)


def doctor() -> int:
    table = Table(title=t("doctor.header"), title_justify="left", show_lines=False)
    table.add_column(t("doctor.engine"), style="bold")
    table.add_column(t("doctor.status"))
    table.add_column(t("doctor.details"), overflow="fold")
    for converter in all_converters():
        try:
            ok = converter.available() and bool(converter_edges(converter))
        except Exception:
            ok = False
        if ok:
            try:
                details = converter.details()
            except Exception as exc:
                details = str(exc)
            table.add_row(converter.name, f"[green]✔ {t('doctor.ok')}[/green]", details)
        else:
            table.add_row(converter.name, f"[yellow]✘ {t('doctor.missing')}[/yellow]", converter.hint)
    console.print(table)
    edges = all_edges()
    console.print(t("doctor.formats", count=len({e.src for e in edges}), targets=len({e.dst for e in edges})))
    return 0


def list_formats() -> int:
    edges = all_edges()
    readable = {e.src for e in edges}
    writable = {e.dst for e in edges}
    table = Table(title=t("formats.header"), title_justify="left")
    table.add_column("id", style="bold")
    table.add_column(t("formats.format"))
    table.add_column(t("formats.ext"), overflow="fold")
    table.add_column(t("formats.read"), justify="center")
    table.add_column(t("formats.write"), justify="center")
    for category in formats.CATEGORIES:
        table.add_section()
        for fmt in formats.FORMATS:
            if fmt.category != category:
                continue
            exts = " ".join(fmt.extensions[:6]) + (" …" if len(fmt.extensions) > 6 else "")
            table.add_row(
                fmt.id,
                format_label(fmt.id),
                exts,
                "[green]✔[/green]" if fmt.id in readable else "[dim]·[/dim]",
                "[green]✔[/green]" if fmt.id in writable else "[dim]·[/dim]",
            )
    console.print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
