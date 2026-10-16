"""Archives and folders: ZIP, 7z, TAR (gz/bz2/xz), plus RAR/ISO/CAB extraction with 7-Zip."""

from __future__ import annotations

import os
import posixpath
import shutil
import stat
import tarfile
import time
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .. import tools
from .base import ConversionError, Converter, Edge

WRITABLE = ("zip", "7z", "tar", "tgz", "tbz2", "txz", "cbz")
READABLE = ("zip", "7z", "tar", "tgz", "tbz2", "txz", "cbz")
NEEDS_7Z_PROGRAM = ("rar", "iso", "cab")
TAR_MODES = {"tar": "w", "tgz": "w:gz", "tbz2": "w:bz2", "txz": "w:xz"}
# ZIP has no portable way to store links, so linked folders go in with their contents.
FOLLOWS_LINKS = ("zip", "cbz")
WINDOWS = os.name == "nt"
# Python 3.10.12, 3.11.4 and later can extract TAR archives safely with the "data" filter.
TAR_DATA_FILTER = hasattr(tarfile, "data_filter")
# Names Windows cannot create (the rules of ntpath.isreserved in Python 3.13).
WINDOWS_BAD_CHARS = frozenset('<>:"|?*' + "".join(map(chr, range(32))))
WINDOWS_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{d}{n}" for d in ("COM", "LPT") for n in "123456789¹²³"}
)
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # a Windows junction


def _check_member(dest: Path, name: str) -> None:
    target = (dest / name).resolve()
    if not target.is_relative_to(dest.resolve()):
        raise ConversionError(f"unsafe path inside the archive: {name}")


def _parts(name: str, resolve: bool = True) -> list[str]:
    """The folders and file name of a member, with ``..`` applied unless ``resolve`` is false."""
    path = name.replace("\\", "/") if WINDOWS else name
    if resolve:
        path = posixpath.normpath(path)
    return [part for part in path.split("/") if part not in ("", ".")]


def _windows_reserved(part: str) -> bool:
    if part.endswith((".", " ")):
        return part not in (".", "..")
    return bool(WINDOWS_BAD_CHARS.intersection(part)) or part.partition(".")[0].rstrip(" ").upper() in WINDOWS_DEVICES


def _ignores_case(folder: Path) -> bool:
    """Whether the file system holding ``folder`` takes README and readme as the same name."""
    probe = folder / "Transcript-Case-Probe"
    probe.touch()
    try:
        return (folder / probe.name.lower()).exists()
    finally:
        probe.unlink()


def _check_names(dest: Path, names: Iterable[str]) -> None:
    """Refuse names that extracting into ``dest`` would silently merge, rename or turn into something else."""
    fold = _ignores_case(dest)
    seen: dict[str, str] = {}
    for name in names:
        parts = _parts(name)
        if WINDOWS and any(map(_windows_reserved, parts)):
            raise ConversionError(f"the archive has a name that Windows cannot store: {name}")
        if not fold:
            continue
        for depth in range(1, len(parts) + 1):
            path = "/".join(parts[:depth])
            # NFC as well: macOS also takes composed and decomposed accents as the same name.
            other = seen.setdefault(unicodedata.normalize("NFC", path).casefold(), path)
            if other != path:
                raise ConversionError(
                    f"the archive has names that differ only in upper/lower case, which this computer takes as the same: "
                    f"{other}, {path}"
                )


def _check_7z_links(files: list) -> None:
    """Refuse members written through a link (``link/file``) or over one: they could land anywhere."""
    named = [("/".join(_parts(f.filename)), f) for f in files]
    links = {name for name, f in named if f.is_symlink or f.is_junction}
    counts = Counter(name for name, _ in named)
    for name, f in named:
        parts = _parts(f.filename, resolve=False)
        through = any(posixpath.normpath("/".join(parts[:depth])) in links for depth in range(1, len(parts)))
        if through or (name in links and counts[name] > 1):
            raise ConversionError(f"unsafe link inside the archive: {f.filename}")


def _plain_members(dest: Path, members: list[tarfile.TarInfo]) -> list[tarfile.TarInfo]:
    """The ``data`` filter for Pythons without it: only files and folders, without special permissions."""
    for member in members:
        _check_member(dest, member.name)
        if not (member.isfile() or member.isdir()):
            raise ConversionError(
                f"this Python version cannot safely extract links or special files from TAR archives ({member.name}); "
                "update Python to 3.10.12, 3.11.4 or later"
            )
        mode = member.mode if member.mode & stat.S_IXUSR else member.mode & ~0o111
        member.mode = 0o755 if member.isdir() else (mode | 0o600) & 0o755
    return members


def _listed_names(listing: str) -> list[str]:
    """Member names in the output of ``7z l -slt``: the "Path = " lines after the archive's own."""
    members = listing.partition("\n----------")[2]
    return [line[len("Path = ") :] for line in members.splitlines() if line.startswith("Path = ")]


def _is_link(st: os.stat_result) -> bool:
    """A symbolic link, or a Windows junction (which ``lstat`` reports as a folder)."""
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) == IO_REPARSE_TAG_MOUNT_POINT


def _raise(exc: OSError) -> None:
    raise exc


def _settle(dest: Path) -> None:
    """Refuse links leading outside ``dest`` whatever the extractor did, and make everything owner-writable.

    py7zr only checks links since 1.1.2, and 7-Zip may create them too. Read-only entries (7z and RAR
    keep that attribute) would make moving the result to another drive, or deleting it, fail on Windows.
    """
    root = Path(os.path.realpath(dest))
    for current, folders, files in os.walk(dest, onerror=_raise):
        links = set()
        for name in folders + files:
            path = os.path.join(current, name)
            st = os.lstat(path)
            if _is_link(st):
                links.add(name)
                if not Path(os.path.realpath(path)).is_relative_to(root):
                    raise ConversionError(f"unsafe link inside the archive: {Path(path).relative_to(dest).as_posix()}")
                continue
            mode = stat.S_IMODE(st.st_mode)
            writable = mode | (stat.S_IRWXU if stat.S_ISDIR(st.st_mode) else stat.S_IRUSR | stat.S_IWUSR)
            if writable != mode:
                os.chmod(path, writable)
        folders[:] = [name for name in folders if name not in links]


def extract(src: Path, fmt: str, dest: Path, ctx) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if fmt in ("zip", "cbz"):
            with zipfile.ZipFile(src) as zf:
                names = zf.namelist()
                _check_names(dest, names)
                for name in names:
                    _check_member(dest, name)
                zf.extractall(dest)
        elif fmt in TAR_MODES:
            with tarfile.open(src) as tf:
                members = tf.getmembers()
                _check_names(dest, [member.name for member in members])
                if TAR_DATA_FILTER:
                    tf.extractall(dest, filter="data")
                else:
                    tf.extractall(dest, members=_plain_members(dest, members))
        elif fmt == "7z":
            import py7zr

            with py7zr.SevenZipFile(src, "r") as archive:
                files = list(archive.files)
                _check_names(dest, [f.filename for f in files])
                for f in files:
                    _check_member(dest, f.filename)
                _check_7z_links(files)
                archive.extractall(path=dest)
        else:
            program = tools.sevenzip()
            if not program:
                raise ConversionError("7-Zip is needed to open this archive")
            _check_names(dest, _listed_names(ctx.run([program, "l", "-slt", str(src)], timeout=600).stdout))
            ctx.run([program, "x", "-y", f"-o{dest}", str(src)], timeout=3600)
        _settle(dest)
    except ConversionError:
        raise
    except RuntimeError as exc:  # zipfile: "File is encrypted, password required"
        raise ConversionError(f"cannot extract the archive: {exc}") from exc
    except Exception as exc:
        raise ConversionError(f"cannot extract the archive: {type(exc).__name__}: {exc}") from exc


def walk(root: Path, prefix: str, follow: bool = False) -> list[tuple[Path, str]]:
    """Every folder, file and link below ``root`` with its name inside the archive.

    Links are listed as links, which TAR and 7z store as such. With ``follow`` (for ZIP) a linked folder
    is listed as that folder with its contents, unless it leads back to a folder already being listed.
    """
    root = Path(os.path.realpath(root))
    items = [(root, prefix)] if prefix else []

    def visit(folder: Path, base: str, above: tuple[str, ...]) -> None:
        with os.scandir(folder) as scan:
            entries = sorted(scan, key=lambda entry: entry.name)
        folders = []
        for entry in entries:
            name = f"{base}/{entry.name}" if base else entry.name
            real = os.path.realpath(entry.path) if entry.is_dir() and (follow or not entry.is_symlink()) else None
            if real is None or real in above:
                items.append((Path(entry.path), name))
            else:
                folders.append((Path(real), name, real))
        for path, name, real in folders:
            items.append((path, name))
            visit(path, name, (*above, real))

    visit(root, prefix, (str(root),))
    return items


def _zip_link(zf: zipfile.ZipFile, path: Path, name: str) -> None:
    """Store a link as Info-ZIP does, so that ``unzip`` restores it: Unix file type, target as content."""
    when = min(max(time.localtime(os.lstat(path).st_mtime)[:6], (1980, 1, 1, 0, 0, 0)), (2107, 12, 31, 23, 59, 59))
    info = zipfile.ZipInfo(name, when)
    info.create_system = 3  # Unix
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    zf.writestr(info, os.readlink(path))


def pack(items: list[tuple[Path, str]], dst: Path, fmt: str, ctx) -> None:
    total = max(1, len(items))
    if fmt in ("zip", "cbz"):
        # Without strict timestamps, files from before 1980 are stored as 1980-01-01 instead of failing.
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
            for index, (path, name) in enumerate(items, 1):
                if path.is_symlink() and not path.is_file():
                    _zip_link(zf, path, name)  # broken, or leading back to a folder above it
                else:
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
                if path.is_symlink() and not path.exists():
                    raise ConversionError(f"7z archives cannot hold a link whose target is missing: {name}")
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
        follow = edge.dst in FOLLOWS_LINKS
        if edge.src == "folder":
            items = walk(src, src.name, follow)
        else:
            extracted = ctx.scratch("extract")
            extract(src, edge.src, extracted, ctx)
            if edge.dst == "folder":
                shutil.move(str(extracted), str(dst))
                return dst
            items = walk(extracted, "", follow)
        pack(items, dst, edge.dst, ctx)
        return dst
