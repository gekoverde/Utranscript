"""Regression tests for the workspace cleanup, the delivery of results and program lookup."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from transcript import engine, tools
from transcript.converters.base import Converter, Edge
from transcript.engine import Context, Options, Reporter, Workspace, execute, remove_tree
from transcript.planner import Route

POSIX = os.name == "posix"


class Upper(Converter):
    name = "upper"

    def convert(self, src, dst, edge, ctx):
        dst.write_text(src.read_text().upper())
        return dst


class WithMedia(Converter):
    """A document plus the ``<stem>_media`` folder it links to, like ``pandoc --extract-media``."""

    name = "with media"

    def convert(self, src, dst, edge, ctx):
        media = dst.parent / f"{dst.stem}_media"
        media.mkdir()
        (media / "img.txt").write_text(src.read_text())
        dst.write_text(f"see {media.name}/img.txt")
        return dst


class ToFolder(Converter):
    """A folder of files (an extracted archive), one of them read-only."""

    name = "to folder"

    def convert(self, src, dst, edge, ctx):
        dst.mkdir()
        (dst / "a.txt").write_text(src.read_text())
        (dst / "ro.txt").write_text("read-only")
        (dst / "ro.txt").chmod(stat.S_IREAD)
        return dst


def convert(src: Path, out_dir: Path, converter: Converter, dst: str = "md", overwrite: bool = False) -> Path:
    route = Route((Edge(src.suffix[1:], dst, converter, terminal=dst == "folder"),), 1.0)
    with Workspace(out_dir.parent / "ws") as workspace:
        return execute(route, src, out_dir, Context(workspace, Options(), Reporter()), overwrite=overwrite)


def listing(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)).replace(os.sep, "/") for p in folder.rglob("*"))


@pytest.fixture
def src(tmp_path) -> Path:
    (tmp_path / "in").mkdir()
    path = tmp_path / "in" / "note.txt"
    path.write_text("new")
    return path


# --- remove_tree -------------------------------------------------------------------------------


def test_remove_tree_deletes_read_only_files_and_folders(tmp_path):
    root = tmp_path / "tree"
    (root / "locked" / "deeper").mkdir(parents=True)
    for folder in (root / "locked", root / "locked" / "deeper"):
        (folder / "file.txt").write_text("x")
        (folder / "file.txt").chmod(stat.S_IREAD)
    (root / "locked" / "deeper").chmod(0o500 if POSIX else stat.S_IREAD)
    (root / "locked").chmod(0o555 if POSIX else stat.S_IREAD)
    assert remove_tree(root) is True
    assert not root.exists()


@pytest.mark.skipif(not POSIX, reason="POSIX permission bits")
def test_unlock_handler_keeps_folders_readable_and_never_calls_open_again(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    (folder / "file.txt").write_text("x")
    folder.chmod(0o500)
    try:
        # rmtree reports a folder it could not open with os.open: calling os.open(path) again raised
        # TypeError, and chmod(S_IWRITE) left the folder at 0o200, unreadable.
        engine._unlock_and_retry(os.open, str(folder), PermissionError())
        assert stat.S_IMODE(folder.stat().st_mode) & 0o700 == 0o700
        engine._unlock_and_retry(os.unlink, str(folder / "file.txt"), PermissionError())
        assert not (folder / "file.txt").exists()
    finally:
        folder.chmod(0o700)


def test_remove_tree_survives_folders_it_cannot_open(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "file.txt").write_text("x")
    real_open = os.open
    refused = []

    def open_once(path, flags, *args, **kwargs):
        if str(path) in ("sub", str(root / "sub")) and not refused:
            refused.append(path)
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_once)
    assert remove_tree(root) is True
    assert not root.exists()


def test_workspace_reports_whether_it_was_removed(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "ws")
    with workspace as path:
        (path / "file.txt").write_text("x")
    assert workspace.removed is True
    assert not path.exists()
    monkeypatch.setattr(engine, "remove_tree", lambda path: False)
    with workspace:
        pass
    assert workspace.removed is False


def test_remove_tree_never_raises(tmp_path, monkeypatch):
    folder = tmp_path / "tree"
    folder.mkdir()

    def broken(*args, **kwargs):
        raise TypeError("open() missing required argument 'flags'")

    monkeypatch.setattr(shutil, "rmtree", broken)
    assert remove_tree(folder, attempts=1) is False
    assert folder.exists()


# --- delivering the result ---------------------------------------------------------------------


def to_another_drive(monkeypatch):
    """Make every rename fail like a move between drives, so results are copied."""

    def rename(a, b, *args, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "rename", rename)


def disk_full_after_some_bytes(monkeypatch):
    def copy2(a, b, *args, **kwargs):
        Path(b).write_text("trunc")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copy2", copy2)


@pytest.mark.parametrize("overwrite", [False, True])
def test_failed_copy_leaves_no_partial_file_and_keeps_the_old_one(tmp_path, src, monkeypatch, overwrite):
    out = tmp_path / "out"
    out.mkdir()
    (out / "note.md").write_text("old")
    to_another_drive(monkeypatch)
    disk_full_after_some_bytes(monkeypatch)
    with pytest.raises(OSError):
        convert(src, out, Upper(), overwrite=overwrite)
    assert listing(out) == ["note.md"]
    assert (out / "note.md").read_text() == "old"
    assert list((tmp_path / "ws").iterdir()) == []


def test_overwrite_replaces_a_file_copied_from_another_drive(tmp_path, src, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "note.md").write_text("old")
    to_another_drive(monkeypatch)
    result = convert(src, out, Upper(), overwrite=True)
    assert result == out / "note.md"
    assert result.read_text() == "NEW"
    assert listing(out) == ["note.md"]


def test_folder_from_another_drive_with_read_only_files(tmp_path, src, monkeypatch):
    out = tmp_path / "out"
    route = Route((Edge("txt", "folder", ToFolder(), terminal=True),), 1.0)
    real_unlink = os.unlink

    def windows_unlink(path, *, dir_fd=None):  # Windows refuses to delete read-only files
        if not os.lstat(path, dir_fd=dir_fd).st_mode & stat.S_IWUSR:
            raise PermissionError(errno.EACCES, "Access is denied", path)
        real_unlink(path, dir_fd=dir_fd)

    with Workspace(tmp_path / "ws") as workspace:
        with monkeypatch.context() as m:
            to_another_drive(m)
            m.setattr(os, "unlink", windows_unlink)
            m.setattr(tools, "WINDOWS", True)
            result = execute(route, src, out, Context(workspace, Options(), Reporter()))
            assert list(workspace.rglob("*.txt")) == []  # the copied source was deleted too
    assert result == out / "note"
    assert listing(out) == ["note", "note/a.txt", "note/ro.txt"]
    assert (result / "a.txt").read_text() == "new"


def test_overwrite_replaces_the_media_folder_of_the_document(tmp_path, src):
    out = tmp_path / "out"
    out.mkdir()
    (out / "note.md").write_text("old document")
    (out / "note_media").mkdir()
    (out / "note_media" / "img.txt").write_text("old image")
    (out / "note_media" / "stale.txt").write_text("from the old document")
    result = convert(src, out, WithMedia(), overwrite=True)
    assert result == out / "note.md"
    assert result.read_text() == "see note_media/img.txt"
    assert listing(out) == ["note.md", "note_media", "note_media/img.txt"]
    assert (out / "note_media" / "img.txt").read_text() == "new"


def test_without_overwrite_document_and_media_folder_get_the_same_new_name(tmp_path, src):
    out = tmp_path / "out"
    (out / "note_media").mkdir(parents=True)
    result = convert(src, out, WithMedia())
    assert result.name == "note (1).md"
    assert result.read_text() == "see note (1)_media/img.txt"
    assert (out / "note (1)_media" / "img.txt").read_text() == "new"


def test_overwrite_is_all_or_nothing(tmp_path, src, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "note.md").write_text("old document")
    (out / "note_media").mkdir()
    (out / "note_media" / "img.txt").write_text("old image")
    real_replace = os.replace

    def replace(a, b, *args, **kwargs):
        if Path(b) == out / "note_media" and Path(a).parent.name == "new":  # e.g. a locked folder on Windows
            raise PermissionError(errno.EACCES, "Access is denied", str(b))
        return real_replace(a, b, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(PermissionError):
        convert(src, out, WithMedia(), overwrite=True)
    assert listing(out) == ["note.md", "note_media", "note_media/img.txt"]
    assert (out / "note.md").read_text() == "old document"
    assert (out / "note_media" / "img.txt").read_text() == "old image"


def test_overwrite_never_replaces_a_media_folder_holding_the_source(tmp_path):
    out = tmp_path / "out"
    (out / "note_media").mkdir(parents=True)
    src = out / "note_media" / "note.txt"
    src.write_text("source")
    result = convert(src, out, WithMedia(), overwrite=True)
    assert src.read_text() == "source"
    assert result.name == "note (1).md"
    assert result.read_text() == "see note (1)_media/img.txt"


def test_overwrite_never_replaces_the_folder_holding_the_source(tmp_path):
    out = tmp_path / "out"
    (out / "backup").mkdir(parents=True)
    src = out / "backup" / "backup.txt"
    src.write_text("source")
    result = convert(src, out, ToFolder(), dst="folder", overwrite=True)
    assert src.read_text() == "source"
    assert result == out / "backup (1)"
    assert (result / "a.txt").read_text() == "source"


def test_overwrite_compares_files_by_identity(tmp_path, src):
    out = tmp_path / "out"
    out.mkdir()
    try:
        os.link(src, out / "note.txt")  # the same file under another path
    except OSError:
        pytest.skip("hard links are not supported here")
    result = convert(src, out, Upper(), dst="txt", overwrite=True)
    assert result.name == "note (1).txt"
    assert src.read_text() == "new"


def test_overwrite_keeps_the_source_on_case_insensitive_file_systems(tmp_path):
    (tmp_path / "dir").mkdir()
    if not (tmp_path / "DIR").exists():
        pytest.skip("the file system is case-sensitive")
    src = tmp_path / "dir" / "note.txt"
    src.write_text("new")
    result = convert(src, tmp_path / "DIR", Upper(), dst="txt", overwrite=True)
    assert src.read_text() == "new"
    assert result.name == "note (1).txt"


# --- program lookup ----------------------------------------------------------------------------


def test_programs_in_the_current_directory_are_never_used_on_windows(tmp_path, monkeypatch):
    cwd, real = tmp_path / "downloads", tmp_path / "bin"
    for folder in (cwd, real):
        folder.mkdir()
        (folder / "ffmpeg.exe").write_bytes(b"")
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(tools, "WINDOWS", True)
    monkeypatch.setenv("PATHEXT", ".exe")
    monkeypatch.setenv("NoDefaultCurrentDirectoryInExePath", "x")
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath")
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", "relative", str(cwd)]))
    assert tools.which("ffmpeg") is None
    assert tools.find_program(["ffmpeg"]) is None
    assert os.environ["NoDefaultCurrentDirectoryInExePath"] == "1"
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(cwd), str(real)]))
    expected = os.path.join(str(real), "ffmpeg.exe")
    assert tools.which("ffmpeg") == expected
    assert tools.find_program(["ffmpeg"]) == expected
    monkeypatch.setenv("TRANSCRIPT_TEST_FFMPEG", "ffmpeg")
    assert tools.find_program([], "TRANSCRIPT_TEST_FFMPEG") == expected


# --- packaging ---------------------------------------------------------------------------------


def test_dependencies_without_windows_arm_wheels_are_skipped_there():
    markers = pytest.importorskip("packaging.requirements")
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    deps = {r.name: r for r in map(markers.Requirement, tomllib.loads(pyproject.read_text("utf-8"))["project"]["dependencies"])}
    for name in ("typst", "pypandoc_binary"):
        marker = deps[name].marker
        assert not marker.evaluate({"sys_platform": "win32", "platform_machine": "ARM64"})
        assert marker.evaluate({"sys_platform": "win32", "platform_machine": "AMD64"})
        assert marker.evaluate({"sys_platform": "linux", "platform_machine": "aarch64"})
    assert deps["py7zr"].specifier.contains("1.1.2") and not deps["py7zr"].specifier.contains("1.1.1")
