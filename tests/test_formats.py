from pathlib import Path

import pytest

from transcript import formats


@pytest.mark.parametrize(
    "name, expected",
    [
        ("informe.docx", "docx"),
        ("FOTO.JPEG", "jpg"),
        ("IMG_0001.HEIC", "heic"),
        ("copia.tar.gz", "tgz"),
        ("copia.tgz", "tgz"),
        ("datos.yml", "yaml"),
        ("pelicula.mkv", "mkv"),
        ("cancion.m4b", "m4a"),
        ("script.py", "code"),
        ("Dockerfile", "code"),
        ("subtitulos.srt", "srt"),
        ("DSC_0001.NEF", "raw"),
        ("fuente.woff2", "woff2"),
    ],
)
def test_detect_by_extension(tmp_path, name, expected):
    path = tmp_path / name
    path.write_bytes(b"x")
    assert formats.detect(path) == expected


def test_detect_folder(tmp_path):
    assert formats.detect(tmp_path) == "folder"


@pytest.mark.parametrize(
    "content, expected",
    [
        (b"%PDF-1.7\n", "pdf"),
        (b"\x89PNG\r\n\x1a\n" + b"\0" * 20, "png"),
        (b"\xff\xd8\xff\xe0" + b"\0" * 20, "jpg"),
        (b"GIF89a" + b"\0" * 20, "gif"),
        (b"RIFF\0\0\0\0WAVEfmt ", "wav"),
        (b"RIFF\0\0\0\0WEBPVP8 ", "webp"),
        (b"\0\0\0\x18ftypheic" + b"\0" * 8, "heic"),
        (b"\0\0\0\x18ftypisom" + b"\0" * 8, "mp4"),
        (b"ID3\x04\0\0\0\0\0\0", "mp3"),
        (b"<!DOCTYPE html><html></html>", "html"),
        (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>', "svg"),
        (b'{"a": 1}', "json"),
        ("hola, qué tal\n".encode("cp1252"), "txt"),
        (b"\0\x01\x02\x03binary", None),
    ],
)
def test_sniff_unknown_extension(tmp_path, content, expected):
    path = tmp_path / "file.unknownext"
    path.write_bytes(content)
    assert formats.detect(path) == expected


def test_sniff_office_zip(tmp_path):
    import zipfile

    path = tmp_path / "document.bin"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w/>")
    assert formats.detect(path) == "docx"


def test_ts_is_typescript_or_video(tmp_path):
    code = tmp_path / "app.ts"
    code.write_text("const x: number = 1;\n")
    video = tmp_path / "clip.ts"
    video.write_bytes((b"\x47" + b"\0" * 187) * 3)
    assert formats.detect(code) == "code"
    assert formats.detect(video) == "ts"


@pytest.mark.parametrize(
    "name, stem, ext",
    [("a.tar.gz", "a", ".tar.gz"), ("my.report.pdf", "my.report", ".pdf"), ("README", "README", ""), (".bashrc", ".bashrc", "")],
)
def test_split_name(name, stem, ext):
    assert formats.split_name(Path(name)) == (stem, ext)


def test_lookup():
    assert formats.lookup("PDF") == "pdf"
    assert formats.lookup(".jpeg") == "jpg"
    assert formats.lookup("tar.gz") == "tgz"
    assert formats.lookup("nope") is None


def test_catalogue_is_consistent():
    ids = [f.id for f in formats.FORMATS]
    assert len(ids) == len(set(ids))
    assert all(f.category in formats.CATEGORIES for f in formats.FORMATS)
    assert all(f.ext or f.id == "folder" for f in formats.FORMATS)
