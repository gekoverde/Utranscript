"""Archives and folders: ZIP, 7z, TAR (gz/bz2/xz), plus RAR/ISO/CAB extraction with 7-Zip."""

from __future__ import annotations

import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from .. import tools
from .base import ConversionError, Converter, Edge

WRITABLE = ("zip", "7z", "tar", "tgz", "tbz2", "txz", "cbz")
READABLE = ("zip", "7z", "tar", "tgz", "tbz2", "txz", "cbz")
NEEDS_7Z_PROGRAM = ("rar", "iso", "cab")
TAR_MODES = {"tar": "w", "tgz": "w:gz", "tbz2": "w:bz2", "txz": "w:xz"}


def _check_member(dest: Path, name: str) -> None:
    target = (dest / name).resolve()
    if not target.is_relative_to(dest.resolve()):
        raise ConversionError(f"unsafe path inside the archive: {name}")


def extract(src: Path, fmt: str, dest: Path, ctx) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if fmt in ("zip", "cbz"):
            with zipfile.ZipFile(src) as zf:
                for name in zf.namelist():
                    _check_member(dest, name)
                zf.extractall(dest)
        elif fmt in TAR_MODES:
            with tarfile.open(src) as tf:
                if hasattr(tarfile, "data_filter"):
                    tf.extractall(dest, filter="data")
                else:
                    for member in tf.getmembers():
                        _check_member(dest, member.name)
                        if member.issym() or member.islnk():
                            _check_member(dest, os.path.join(os.path.dirname(member.name), member.linkname))
                    tf.extractall(dest)
        elif fmt == "7z":
            import py7zr

            with py7zr.SevenZipFile(src, "r") as archive:
                for name in archive.getnames():
                    _check_member(dest, name)
                archive.extractall(path=dest)
        else:
            program = tools.sevenzip()
            if not program:
                raise ConversionError("7-Zip is needed to open this archive")
            ctx.run([program, "x", "-y", f"-o{dest}", str(src)], timeout=3600)
    except ConversionError:
        raise
    except RuntimeError as exc:  # zipfile: "File is encrypted, password required"
        raise ConversionError(f"cannot extract the archive: {exc}") from exc
    except Exception as exc:
        raise ConversionError(f"cannot extract the archive: {type(exc).__name__}: {exc}") from exc


def walk(root: Path, prefix: str) -> list[tuple[Path, str]]:
    """Every folder and file below ``root`` with its name inside the archive."""
    items = []
    for current, dirs, files in os.walk(root):
        dirs.sort()
        rel = Path(current).relative_to(root)
        base = Path(prefix) / rel if prefix else rel
        if str(base) not in (".", ""):
            items.append((Path(current), base.as_posix()))
        for name in sorted(files):
            items.append((Path(current) / name, (base / name).as_posix() if str(base) != "." else name))
    return items


def pack(items: list[tuple[Path, str]], dst: Path, fmt: str, ctx) -> None:
    total = max(1, len(items))
    if fmt in ("zip", "cbz"):
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            for index, (path, name) in enumerate(items, 1):
                zf.write(path, name + "/" if path.is_dir() else name)
                ctx.progress(index, total)
    elif fmt in TAR_MODES:
        with tarfile.open(dst, TAR_MODES[fmt]) as tf:
            for index, (path, name) in enumerate(items, 1):
                tf.add(path, name, recursive=False)
                ctx.progress(index, total)
    elif fmt == "7z":
        import py7zr

        with py7zr.SevenZipFile(dst, "w") as archive:
            for index, (path, name) in enumerate(items, 1):
                archive.write(path, name)
                ctx.progress(index, total)
    else:
        raise ConversionError(f"cannot create {fmt} archives")


class ArchiveConverter(Converter):
    name = "Transcript archives"

    def details(self) -> str:
        program = tools.sevenzip()
        return f"7-Zip: {program}" if program else "RAR/ISO/CAB need 7-Zip (winget install 7zip.7zip / sudo apt install 7zip)"

    def edges(self):
        readable = list(READABLE) + (list(NEEDS_7Z_PROGRAM) if tools.sevenzip() else [])
        edges = self.matrix(readable, WRITABLE)
        edges += [self.edge(fmt, "folder", terminal=True) for fmt in readable]
        edges += [self.edge("folder", fmt) for fmt in WRITABLE]
        return edges

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        if edge.src == "folder":
            items = walk(src, src.name)
        else:
            extracted = ctx.scratch("extract")
            extract(src, edge.src, extracted, ctx)
            if edge.dst == "folder":
                shutil.move(str(extracted), str(dst))
                return dst
            items = walk(extracted, "")
        pack(items, dst, edge.dst, ctx)
        return dst
