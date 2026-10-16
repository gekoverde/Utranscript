"""Locating and running the external programs Transcript can use."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence
from functools import cache
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


class ConversionError(Exception):
    """A conversion step failed. The message is shown to the user."""


def _program_files() -> list[Path]:
    roots = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(var)
        if value:
            roots.append(Path(value))
    return roots


def find_program(names: Sequence[str], env_var: str | None = None, extra: Sequence[Path] = ()) -> str | None:
    """Find an executable: environment variable override, then PATH, then well-known locations."""
    if env_var and os.environ.get(env_var):
        candidate = os.environ[env_var]
        found = candidate if Path(candidate).is_file() else which(candidate)
        if found:
            return found
    for name in names:
        found = which(name)
        if found:
            return found
    for path in extra:
        if path.is_file():
            return str(path)
    return None


def which(name: str) -> str | None:
    """``shutil.which``, except that on Windows a program in the current directory is never used.

    Windows looks in the current directory before PATH, so an ``ffmpeg.exe`` planted next to the
    user's files would run instead of the real one.
    """
    if not WINDOWS or os.path.dirname(name):
        return shutil.which(name)
    os.environ.setdefault("NoDefaultCurrentDirectoryInExePath", "1")  # the same rule for Python 3.12+ and children
    exts = [e for e in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(os.pathsep) if e]
    files = [name] if any(name.lower().endswith(e.lower()) for e in exts) else [name + e for e in exts]
    cwd = os.path.normcase(os.path.abspath(os.getcwd()))
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        folder = folder.strip().strip('"')
        # '', '.' and other relative entries also point into the current directory.
        if not os.path.isabs(folder) or os.path.normcase(os.path.abspath(folder)) == cwd:
            continue
        for file in files:
            path = os.path.join(folder, file)
            if os.path.isfile(path):
                return path
    return None


@cache
def ffmpeg() -> str | None:
    found = find_program(["ffmpeg"], "TRANSCRIPT_FFMPEG")
    if found:
        return found
    try:  # bundled static build from the imageio-ffmpeg package
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


@cache
def pandoc() -> str | None:
    if os.environ.get("TRANSCRIPT_PANDOC"):
        return find_program([], "TRANSCRIPT_PANDOC")
    try:  # the pypandoc_binary package ships a recent pandoc
        import importlib.util

        spec = importlib.util.find_spec("pypandoc")
        if spec and spec.origin:
            bundled = Path(spec.origin).parent / "files" / ("pandoc.exe" if WINDOWS else "pandoc")
            if bundled.is_file():
                return str(bundled)
    except Exception:
        pass
    return find_program(["pandoc"])


@cache
def soffice() -> str | None:
    extra = []
    for root in _program_files():
        # soffice.com is the console flavour on Windows: it waits for the conversion to finish.
        extra += [root / "LibreOffice" / "program" / "soffice.com", root / "LibreOffice" / "program" / "soffice.exe"]
    if MACOS:
        extra.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    names = ["soffice.com", "soffice"] if WINDOWS else ["soffice", "libreoffice"]
    return find_program(names, "TRANSCRIPT_SOFFICE", extra)


@cache
def tesseract() -> str | None:
    extra = [root / "Tesseract-OCR" / "tesseract.exe" for root in _program_files()]
    return find_program(["tesseract"], "TRANSCRIPT_TESSERACT", extra)


@cache
def ebook_convert() -> str | None:
    extra = [root / "Calibre2" / "ebook-convert.exe" for root in _program_files()]
    if MACOS:
        extra.append(Path("/Applications/calibre.app/Contents/MacOS/ebook-convert"))
    return find_program(["ebook-convert"], "TRANSCRIPT_EBOOK_CONVERT", extra)


@cache
def sevenzip() -> str | None:
    extra = [root / "7-Zip" / "7z.exe" for root in _program_files()]
    return find_program(["7z", "7zz", "7za"], "TRANSCRIPT_7Z", extra)


@cache
def rsvg_convert() -> str | None:
    return find_program(["rsvg-convert"])


@cache
def inkscape() -> str | None:
    extra = [root / "Inkscape" / "bin" / "inkscape.exe" for root in _program_files()]
    if MACOS:
        extra.append(Path("/Applications/Inkscape.app/Contents/MacOS/inkscape"))
    return find_program(["inkscape"], None, extra)


def spawn_options() -> dict:
    """Extra ``Popen`` arguments so that a child and everything it starts can be killed together.

    On POSIX the child gets its own session (LibreOffice, for instance, runs ``soffice.bin``
    as a grandchild). On Windows the child stays in the console group so that Ctrl+C still
    reaches it and ``wait()`` returns promptly.
    """
    return {} if WINDOWS else {"start_new_session": True}


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill a child started with ``spawn_options()`` and all of its descendants."""
    try:
        if WINDOWS:
            if proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    verbose: bool = False,
    log=None,
) -> subprocess.CompletedProcess:
    """Run a command, raising ConversionError with the tail of its output when it fails.

    If the command times out or Transcript is interrupted, the whole process tree is killed
    so that nothing keeps writing into the temporary workspace after it is removed.
    """
    if verbose and log:
        log(" ".join(_quote(c) for c in cmd))
    try:
        proc = subprocess.Popen(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            **spawn_options(),
        )
    except FileNotFoundError as exc:
        raise ConversionError(f"program not found: {cmd[0]}") from exc
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        kill_tree(proc)
        raise ConversionError(f"{Path(cmd[0]).name} timed out") from exc
    except BaseException:
        kill_tree(proc)
        raise
    if proc.returncode != 0:
        raise ConversionError(f"{Path(cmd[0]).name} failed: {tail(stderr or stdout)}")
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def tail(text: str, lines: int = 8) -> str:
    parts = [line for line in (text or "").strip().splitlines() if line.strip()]
    return "\n".join(parts[-lines:]) or "(no output)"


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg
