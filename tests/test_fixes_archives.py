"""Regression tests for archives: linked folders, names the computer cannot store, links and special
files leading out of the extraction folder, ZIP dates before 1980 and read-only entries."""

from __future__ import annotations

import io
import os
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from transcript.converters import archives
from transcript.tools import ConversionError

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")  # tarfile without a filter (3.12/3.13)


@pytest.fixture
def symlinks(tmp_path):
    """Skip when this computer does not let us create links (Windows without developer mode)."""
    probe = tmp_path / "_link_probe"
    try:
        probe.symlink_to("x")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available")
    probe.unlink()


def make_archive(path: Path, fmt: str, entries: dict[str, bytes]) -> Path:
    if fmt == "zip":
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
    elif fmt == "tar":
        tar_with(path, *((member(name), data) for name, data in entries.items()))
    else:
        import py7zr

        with py7zr.SevenZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr(data, name)
    return path


def member(name: str, kind: bytes = tarfile.REGTYPE, linkname: str = "", mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type, info.linkname, info.mode, info.mtime = kind, linkname, mode, 2 * 86400
    return info


def tar_with(path: Path, *members: tuple[tarfile.TarInfo, bytes | None]) -> Path:
    with tarfile.open(path, "w") as tf:
        for info, data in members:
            info.size = len(data or b"")
            tf.addfile(info, io.BytesIO(data) if data else None)
    return path


# folders with links --------------------------------------------------------------------------


def test_linked_folders_are_kept(samples, convert, symlinks):
    import py7zr

    proj = samples / "proj"
    (proj / "real").mkdir(parents=True)
    (proj / "real" / "f.txt").write_text("hi")
    (proj / "alias").symlink_to("real", target_is_directory=True)
    (proj / "real" / "back").symlink_to("..", target_is_directory=True)

    with tarfile.open(convert(proj, "tar")) as tf:
        assert tf.getmember("proj/alias").issym() and tf.getmember("proj/alias").linkname == "real"
        assert tf.getmember("proj/real/back").issym()
    seven = convert(proj, "7z")
    with py7zr.SevenZipFile(seven) as archive:
        assert {f.filename for f in archive.files if f.is_symlink} == {"proj/alias", "proj/real/back"}
    with zipfile.ZipFile(convert(proj, "zip")) as zf:
        assert zf.read("proj/alias/f.txt") == b"hi"  # ZIP stores the linked folder with its contents
        loop = zf.getinfo("proj/alias/back")  # ...but a link back to a folder above it stays a link
        assert stat.S_ISLNK(loop.external_attr >> 16) and zf.read(loop) == b".."
    extracted = convert(seven, "folder")
    assert (extracted / "proj" / "alias" / "f.txt").read_text() == "hi"


def test_zip_accepts_files_older_than_1980(samples, convert):
    folder = samples / "old"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    os.utime(folder / "a.txt", (2 * 86400, 2 * 86400))
    with zipfile.ZipFile(convert(folder, "zip")) as zf:
        assert zf.getinfo("old/a.txt").date_time == (1980, 1, 1, 0, 0, 0)
    bundle = tar_with(samples / "bundle.tar", (member("b.txt"), b"b"))
    with zipfile.ZipFile(convert(bundle, "zip")) as zf:
        assert zf.read("b.txt") == b"b"


# names this computer cannot store --------------------------------------------------------------


def test_case_probe_matches_the_file_system(tmp_path):
    (tmp_path / "Probe").touch()
    folder = tmp_path / "folder"
    folder.mkdir()
    assert archives._ignores_case(folder) is (tmp_path / "probe").exists()
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("fmt", ["zip", "tar", "7z"])
@pytest.mark.parametrize("names", [("README", "readme"), ("Docs/a.txt", "docs/b.txt")])
def test_names_differing_only_in_case_are_refused(samples, tmp_path, monkeypatch, fmt, names):
    monkeypatch.setattr(archives, "_ignores_case", lambda folder: True)
    archive = make_archive(samples / f"case.{fmt}", fmt, {name: b"x" for name in names})
    dest = tmp_path / "dest"
    with pytest.raises(ConversionError, match="differ only in upper/lower case"):
        archives.extract(archive, fmt, dest, None)
    assert list(dest.iterdir()) == []


def test_case_collision_fails_the_conversion(samples, tmp_path, monkeypatch):
    from transcript.cli import main

    monkeypatch.setattr(archives, "_ignores_case", lambda folder: True)
    archive = make_archive(samples / "case.zip", "zip", {"README": b"1", "readme": b"2"})
    assert main([str(archive), "--to", "tar", "-o", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out" / "case.tar").exists()


@pytest.mark.parametrize(
    "name", ["a:b.txt", "con.txt", "sub/NUL", "Aux.tar.gz", "LPT1", "what?.txt", "dot.", "space ", "c\x01.txt"]
)
def test_names_windows_cannot_store_are_refused(samples, tmp_path, monkeypatch, name):
    monkeypatch.setattr(archives, "WINDOWS", True)
    archive = make_archive(samples / "names.zip", "zip", {name: b"x"})
    with pytest.raises(ConversionError, match="Windows cannot store"):
        archives.extract(archive, "zip", tmp_path / "dest", None)


def test_valid_windows_names_are_extracted(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "WINDOWS", True)
    names = ["console.txt", "com10.txt", "x.con", "sub/nul-ish.txt"]
    archive = make_archive(samples / "names.tar", "tar", {name: b"x" for name in names})
    archives.extract(archive, "tar", tmp_path / "dest", None)
    assert all((tmp_path / "dest" / name).read_bytes() == b"x" for name in names)


def test_7zip_listing_is_checked_before_extracting(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "_ignores_case", lambda folder: True)
    monkeypatch.setattr(archives.tools, "sevenzip", lambda: "7z")
    listing = (
        "7-Zip 23.01\n\nListing archive: x.rar\n\n--\nPath = x.rar\nType = Rar\n\n----------\n"
        "Path = Docs\nFolder = +\n\nPath = Docs/A.txt\nFolder = -\n\nPath = docs/a.txt\nFolder = -\n"
    )
    calls = []

    class Context:
        def run(self, cmd, timeout=None):
            calls.append(cmd[1])
            return subprocess.CompletedProcess(cmd, 0, listing, "")

    assert archives._listed_names(listing) == ["Docs", "Docs/A.txt", "docs/a.txt"]
    with pytest.raises(ConversionError, match="differ only in upper/lower case"):
        archives.extract(samples / "x.rar", "rar", tmp_path / "dest", Context())
    assert calls == ["l"]


# links leading out of the extraction folder ----------------------------------------------------


def test_7z_members_written_through_or_over_a_link_are_refused(samples, tmp_path, symlinks):
    import py7zr

    build = samples / "build"
    (build / "a" / "b").mkdir(parents=True)
    (build / "a" / "b" / "l").symlink_to(os.path.join("..", ".."), target_is_directory=True)
    (build / "p").symlink_to(os.path.join("a", "b", "l", ".."), target_is_directory=True)
    (build / "target.txt").write_text("t")
    (build / "x").symlink_to("target.txt")
    chain, over = samples / "chain.7z", samples / "over.7z"
    with py7zr.SevenZipFile(chain, "w") as archive:
        for name in ("a", "a/b", "a/b/l", "p"):
            archive.write(build / name, name)
        archive.writestr(b"PWNED", "p/escaped.txt")
    with py7zr.SevenZipFile(over, "w") as archive:
        archive.write(build / "x", "x")
        archive.writestr(b"PWNED", "x")

    work = tmp_path / "work"
    for archive, name in ((chain, "p/escaped.txt"), (over, "x")):
        with pytest.raises(ConversionError, match=f"unsafe link inside the archive: {name}$"):
            archives.extract(archive, "7z", work / "dest", None)
    assert sorted(p.name for p in work.rglob("*")) == ["dest"]
    assert (build / "target.txt").read_text() == "t"


def test_links_out_of_the_folder_are_refused_whatever_the_extractor(samples, tmp_path, monkeypatch, symlinks):
    import py7zr

    archive = make_archive(samples / "plain.7z", "7z", {"a.txt": b"a"})

    def careless_extractall(self, path=None, **kwargs):  # what py7zr before 1.1.2 let through
        (Path(path) / "evil").symlink_to(tmp_path, target_is_directory=True)

    monkeypatch.setattr(py7zr.SevenZipFile, "extractall", careless_extractall)
    with pytest.raises(ConversionError, match="unsafe link inside the archive: evil"):
        archives.extract(archive, "7z", tmp_path / "dest", None)


FALLBACK_REFUSED = {
    "symlink chain": [
        (member("a", tarfile.DIRTYPE, mode=0o755), None),
        (member("a/b", tarfile.DIRTYPE, mode=0o755), None),
        (member("a/b/l", tarfile.SYMTYPE, "../.."), None),
        (member("p", tarfile.SYMTYPE, "a/b/l/.."), None),
        (member("p/escaped.txt"), b"PWNED"),
    ],
    "hardlink": [(member("x/y/z/leak", tarfile.LNKTYPE, "../../../secret.txt"), None), (member("x/y/z/leak"), b"PWNED")],
    "fifo": [(member("pipe", tarfile.FIFOTYPE), None)],
    "device": [(member("dev", tarfile.CHRTYPE), None)],
}


@pytest.mark.parametrize("case", FALLBACK_REFUSED)
def test_tar_without_data_filter_refuses_links_and_special_files(samples, tmp_path, monkeypatch, case):
    monkeypatch.setattr(archives, "TAR_DATA_FILTER", False)
    archive = tar_with(samples / "evil.tar", *FALLBACK_REFUSED[case])
    box = tmp_path / "box"
    dest = box / "a" / "b" / "dest"  # the hardlink points three folders above it
    dest.mkdir(parents=True)
    (box / "secret.txt").write_text("secret")
    with pytest.raises(ConversionError, match="cannot safely extract links or special files"):
        archives.extract(archive, "tar", dest, None)
    assert (box / "secret.txt").read_text() == "secret"
    assert sorted(p.relative_to(box).as_posix() for p in box.rglob("*")) == ["a", "a/b", "a/b/dest", "secret.txt"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_tar_without_data_filter_strips_special_permissions(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "TAR_DATA_FILTER", False)
    archive = tar_with(
        samples / "modes.tar",
        (member("d", tarfile.DIRTYPE, mode=0o7777), None),
        (member("d/run", mode=0o6777), b"#!"),
        (member("d/data", mode=0o666), b"x"),
    )
    archives.extract(archive, "tar", tmp_path / "dest", None)
    modes = {name: stat.S_IMODE(os.stat(tmp_path / "dest" / name).st_mode) for name in ("d", "d/run", "d/data")}
    assert modes == {"d": 0o755, "d/run": 0o755, "d/data": 0o644}


# read-only entries -------------------------------------------------------------------------------


def test_extracted_entries_are_left_writable(samples, tmp_path):
    import py7zr

    pkg = samples / "pkg"
    pkg.mkdir()
    (pkg / "ro.txt").write_text("x")
    os.chmod(pkg / "ro.txt", stat.S_IREAD)
    os.chmod(pkg, stat.S_IREAD | stat.S_IEXEC)
    archive = samples / "ro.7z"
    try:
        with py7zr.SevenZipFile(archive, "w") as seven:
            seven.write(pkg, "pkg")
            seven.write(pkg / "ro.txt", "pkg/ro.txt")
    finally:
        os.chmod(pkg, stat.S_IRWXU)
        os.chmod(pkg / "ro.txt", stat.S_IREAD | stat.S_IWRITE)

    archives.extract(archive, "7z", tmp_path / "dest", None)
    for name in ("pkg", "pkg/ro.txt"):
        assert os.stat(tmp_path / "dest" / name).st_mode & stat.S_IWRITE, name
