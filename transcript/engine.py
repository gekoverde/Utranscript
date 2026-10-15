"""Running a conversion route inside a temporary working folder."""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import formats, tools
from .converters.base import Edge
from .planner import Route
from .tools import ConversionError


@dataclass
class Options:
    dpi: int = 150
    lang: str | None = None  # language of the content (OCR, speech recognition)
    model: str | None = None  # speech recognition model (default: small)
    verbose: bool = False


class Reporter:
    """Receives progress information. The terminal UI provides a rich implementation."""

    def step(self, edge: Edge) -> None:
        pass

    def progress(self, done: float, total: float | None = None) -> None:
        pass

    def log(self, message: str) -> None:
        pass

    def finish_step(self, ok: bool = True) -> None:
        pass


class Context:
    """What a converter gets to work with: the temporary folder, options and progress."""

    def __init__(self, workspace: Path, options: Options, reporter: Reporter):
        self.workspace = workspace
        self.options = options
        self.reporter = reporter
        self._scratch = 0

    def scratch(self, name: str = "tmp") -> Path:
        """A fresh folder inside the temporary workspace for intermediate files."""
        self._scratch += 1
        path = self.workspace / f"_{name}{self._scratch}"
        path.mkdir(parents=True)
        return path

    def log(self, message: str) -> None:
        if self.options.verbose:
            self.reporter.log(message)

    def progress(self, done: float, total: float | None = None) -> None:
        self.reporter.progress(done, total)

    def run(self, cmd: Sequence[str], cwd: Path | None = None, timeout: float | None = None):
        return tools.run(cmd, cwd=cwd, timeout=timeout, verbose=self.options.verbose, log=self.reporter.log)


class Workspace:
    """The temporary folder that only exists while Transcript runs."""

    def __init__(self, base: Path | None = None):
        self.base = base or (Path(os.environ["TRANSCRIPT_TMPDIR"]) if os.environ.get("TRANSCRIPT_TMPDIR") else None)
        self.path: Path | None = None

    def __enter__(self) -> Path:
        if self.base:
            self.base.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix="transcript-", dir=self.base))
        return self.path

    def __exit__(self, *exc_info) -> None:
        if self.path is not None:
            remove_tree(self.path)


def remove_tree(path: Path, attempts: int = 5) -> None:
    """Delete a folder, retrying a few times (on Windows files can stay locked for a moment)."""

    def make_writable_and_retry(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    for attempt in range(attempts):
        if not path.exists():
            return
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=make_writable_and_retry)
            else:
                shutil.rmtree(path, onerror=make_writable_and_retry)
        except OSError:
            pass
        if not path.exists():
            return
        time.sleep(0.2 * (attempt + 1))


def output_stem(src: Path, out_dir: Path, route: Route, overwrite: bool) -> str:
    """Pick the name of the result so that nothing existing is ever replaced by accident."""
    stem = src.name if src.is_dir() else formats.split_name(src)[0]
    if overwrite:
        return stem
    ext = formats.get(route.target).ext
    may_be_folder = route.target == "folder" or route.edges[-1].terminal
    n = 0
    while True:
        candidate = stem if n == 0 else f"{stem} ({n})"
        taken = (
            (ext and (out_dir / (candidate + ext)).exists())
            or (out_dir / f"{candidate}_media").exists()
            or (may_be_folder and (out_dir / candidate).exists())
        )
        if not taken:
            return candidate
        n += 1


def first_step_ok(src: Path, ctx: Context):
    """Build the filter the planner uses to ask converters about the actual input file."""
    cache: dict[tuple[int, str, str], bool] = {}

    def check(edge: Edge) -> bool:
        key = (id(edge.converter), edge.src, edge.dst)
        if key not in cache:
            try:
                cache[key] = edge.converter.accepts(src, edge, ctx)
            except Exception:
                cache[key] = False
        return cache[key]

    return check


def execute(route: Route, src: Path, out_dir: Path, ctx: Context, overwrite: bool = False) -> Path:
    """Run every step of ``route`` in the workspace and move the result to ``out_dir``."""
    stem = output_stem(src, out_dir, route, overwrite)
    current = src
    step_dir = ctx.workspace
    for index, edge in enumerate(route.edges, 1):
        if index > 1 and current.is_dir() and edge.src != "folder":
            raise ConversionError(f"{formats.get(edge.src).name} produced several files and cannot be converted further")
        step_dir = ctx.workspace / f"step{index}"
        step_dir.mkdir()
        dst = step_dir / (stem + formats.get(edge.dst).ext)
        ctx.reporter.step(edge)
        ok = False
        try:
            produced = edge.converter.convert(current, dst, edge, ctx)
            ok = True
        finally:
            ctx.reporter.finish_step(ok)
        if produced is None or not produced.exists():
            raise ConversionError(f"{edge.converter.name} did not produce any output")
        current = produced

    out_dir.mkdir(parents=True, exist_ok=True)
    result = None
    for item in sorted(step_dir.iterdir()):
        target = out_dir / item.name
        if target.exists() or target.is_symlink():
            if overwrite and target.is_file() and target.resolve() != src.resolve():
                target.unlink()
            else:
                target = _numbered(target)
        shutil.move(str(item), str(target))
        if item == current:
            result = target
    return result or out_dir / current.name


def _numbered(path: Path) -> Path:
    stem, ext = formats.split_name(path) if not path.is_dir() else (path.name, "")
    n = 1
    while True:
        candidate = path.with_name(f"{stem} ({n}){ext}")
        if not candidate.exists():
            return candidate
        n += 1
