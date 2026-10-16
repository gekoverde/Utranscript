"""Running a conversion route inside a temporary working folder."""

from __future__ import annotations

import contextlib
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
        self._env: dict[str, str] | None = None

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

    def env(self) -> dict[str, str]:
        """Environment for external programs: their own temporary files go inside the workspace."""
        if self._env is None:
            tmp = self.workspace / "_tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            self._env = {**os.environ, "TMPDIR": str(tmp), "TMP": str(tmp), "TEMP": str(tmp)}
        return self._env

    def run(self, cmd: Sequence[str], cwd: Path | None = None, timeout: float | None = None):
        return tools.run(cmd, cwd=cwd, timeout=timeout, env=self.env(), verbose=self.options.verbose, log=self.reporter.log)


class Workspace:
    """The temporary folder that only exists while Transcript runs."""

    def __init__(self, base: Path | None = None):
        self.base = base or (Path(os.environ["TRANSCRIPT_TMPDIR"]) if os.environ.get("TRANSCRIPT_TMPDIR") else None)
        self.path: Path | None = None
        self.removed = False  # whether the folder was really deleted on exit

    def __enter__(self) -> Path:
        if self.base:
            self.base.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix="transcript-", dir=self.base))
        # Temporary files of the Python libraries used by the converters also go inside it.
        library_tmp = self.path / "_tmp"
        library_tmp.mkdir()
        self._previous_tempdir = tempfile.tempdir
        tempfile.tempdir = str(library_tmp)
        return self.path

    def __exit__(self, *exc_info) -> None:
        if self.path is not None:
            tempfile.tempdir = self._previous_tempdir
            self.removed = remove_tree(self.path)


def remove_tree(path: Path, attempts: int = 5) -> bool:
    """Delete a folder, retrying a few times (on Windows files can stay locked for a moment).

    Never raises: returns whether the folder is gone.
    """
    for attempt in range(attempts):
        try:
            if not os.path.lexists(path):
                return True
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=_unlock_and_retry)
            else:
                shutil.rmtree(path, onerror=_unlock_and_retry)
        except Exception:
            pass
        if not os.path.lexists(path):
            return True
        if attempt + 1 < attempts:
            time.sleep(0.2 * (attempt + 1))
    return False


def _unlock_and_retry(func, target, _exc) -> None:
    """``rmtree`` error handler: make ``target`` deletable and retry a failed deletion once."""
    delete = func in (os.unlink, os.remove, os.rmdir)
    try:
        if tools.WINDOWS:
            os.chmod(target, stat.S_IWRITE)  # clears the read-only attribute
        else:
            # Deleting needs u+wx on the folder holding the item, and walking a folder u+rx on it.
            # (S_IWRITE alone would set 0o200 here: a folder that can no longer be read.)
            if delete:
                _allow_user(os.path.dirname(target))
            _allow_user(target)
        if delete:  # a folder that could not be opened or listed is retried by the next rmtree pass
            func(target)
    except Exception:
        pass


def _allow_user(folder: str) -> None:
    """Add u+rwx to ``folder`` if it is a real folder."""
    try:
        mode = os.lstat(folder).st_mode
        if stat.S_ISDIR(mode):
            os.chmod(folder, stat.S_IMODE(mode) | stat.S_IRWXU)
    except OSError:
        pass


def output_stem(src: Path, out_dir: Path, route: Route, overwrite: bool) -> str:
    """Pick the name of the result so that nothing existing is ever replaced by accident.

    With ``overwrite`` an earlier result with the same names is replaced (the document together
    with its ``_media`` folder), unless one of those names is the source or a folder holding it,
    or a folder other than a ``_media`` one.
    """
    stem = src.name if src.is_dir() else formats.split_name(src)[0]
    ext = formats.get(route.target).ext
    may_be_folder = route.target == "folder" or route.edges[-1].terminal
    n = 0
    while True:
        candidate = stem if n == 0 else f"{stem} ({n})"
        names = {f"{candidate}_media": "dir"}
        if ext:
            names[candidate + ext] = "file"
        if may_be_folder:
            names[candidate] = "dir"
        if not any(_taken(out_dir / name, kind, overwrite, (src,)) for name, kind in names.items()):
            return candidate
        n += 1


def _kind(path: Path) -> str:
    if path.is_dir() and not path.is_symlink():
        return "dir"
    return "file" if path.is_file() else "other"


def _taken(path: Path, kind: str, overwrite: bool, keep: Sequence[Path]) -> bool:
    """Whether ``path`` blocks a result of ``kind``: it exists and may not be replaced.

    ``--overwrite`` replaces files, and the ``_media`` folder that goes with a document. Any other
    folder may hold the user's own files (a ``backup`` folder next to ``backup.zip``): it is kept.
    """
    if not os.path.lexists(path):
        return False
    replaceable = kind == "file" or path.name.endswith("_media")
    return not (overwrite and replaceable and _kind(path) == kind and not any(_holds(path, p) for p in keep))


def _holds(path: Path, inner: Path) -> bool:
    """Whether ``path`` is ``inner`` or a folder containing it, by file identity (links, mounts, letter case)."""
    try:
        st = os.stat(path)
        inner = inner.absolute()
        return any(os.path.samestat(st, os.stat(p)) for p in {inner, *inner.parents, *inner.resolve().parents})
    except (OSError, RuntimeError):
        return True  # when in doubt, keep it


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
    moves: list[tuple[Path, Path]] = []
    result = None
    for item in sorted(step_dir.iterdir()):
        target = out_dir / item.name
        if _taken(target, _kind(item), overwrite, (src, ctx.workspace)):
            target = _numbered(target, item.is_dir())
        moves.append((item, target))
        if item == current:
            result = target
    _deliver(moves, out_dir)
    return result or out_dir / current.name


def _deliver(moves: Sequence[tuple[Path, Path]], out_dir: Path) -> None:
    """Move the results to their final names, all or nothing, never leaving a half-written file there.

    Everything is first moved (copied, from another drive) into a hidden folder inside ``out_dir``
    and only then renamed into place, so an earlier result is replaced only by a complete new one,
    and is put back if anything fails.
    """
    staging = Path(tempfile.mkdtemp(prefix=".transcript-", dir=out_dir))
    new, old = staging / "new", staging / "old"
    new.mkdir()
    old.mkdir()
    placed: list[tuple[str, Path]] = []
    ok = False
    try:
        for item, _ in moves:
            _move(item, new / item.name)
        for item, target in moves:
            placed.append((item.name, target))
            # A folder cannot be replaced in one step, and with several results every earlier one is
            # kept until all are in place. A single file is simply replaced atomically.
            if os.path.lexists(target) and (len(moves) > 1 or (new / item.name).is_dir()):
                os.replace(target, old / item.name)
            os.replace(new / item.name, target)
        ok = True
    except BaseException:
        for name, target in reversed(placed):
            with contextlib.suppress(OSError):
                if not os.path.lexists(new / name):  # the new one is already in place: take it back
                    os.replace(target, new / name)
                if os.path.lexists(old / name):
                    os.replace(old / name, target)
        raise
    finally:
        with contextlib.suppress(OSError):
            if ok or not os.listdir(old):  # otherwise it still holds an earlier result that could not be put back
                remove_tree(staging)


def _move(item: Path, dst: Path) -> None:
    """Move ``item`` to the new name ``dst``, copying it when it is on another drive."""
    try:
        os.rename(item, dst)
    except OSError:
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, dst, symlinks=True)
            remove_tree(item)  # unlike shutil.move's rmtree, this copes with read-only files
        else:
            shutil.copy2(item, dst, follow_symlinks=False)
            with contextlib.suppress(OSError):
                item.unlink()


def _numbered(path: Path, is_dir: bool) -> Path:
    stem, ext = (path.name, "") if is_dir else formats.split_name(path)
    n = 1
    while True:
        candidate = path.with_name(f"{stem} ({n}){ext}")
        if not os.path.lexists(candidate):
            return candidate
        n += 1
