"""Regression tests for text encodings and line ends, LibreOffice routes and pandoc conversions."""

from __future__ import annotations

import base64
import os
import re
import zipfile
from pathlib import Path

import pytest
from conftest import make_png

from transcript import tools
from transcript.converters import documents, text
from transcript.converters.data import DataConverter
from transcript.converters.office import LibreOfficeConverter
from transcript.converters.pdf import PdfConverter
from transcript.converters.text import read_text
from transcript.planner import plan

needs_libreoffice = pytest.mark.skipif(tools.soffice() is None, reason="LibreOffice is not installed")
needs_pandoc = pytest.mark.skipif(tools.pandoc() is None, reason="pandoc is not installed")


@pytest.fixture
def windows_newlines(monkeypatch):
    """``Path.write_text`` as on Windows, where "\\n" becomes "\\r\\n" unless ``newline`` says otherwise."""
    original = Path.write_text

    def write_text(self, data, encoding=None, errors=None, newline=None):
        return original(self, data, encoding=encoding, errors=errors, newline="\r\n" if newline is None else newline)

    monkeypatch.setattr(Path, "write_text", write_text)


def read_back(tmp_path: Path, data: bytes) -> str:
    path = tmp_path / "sample.txt"
    path.write_bytes(data)
    return read_text(path)


# read_text -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sample",
    [
        "El niño comió piña.",
        "Señor Muñoz pagó 5€ por el café.",
        "Résumé",
        "Müller",
        "Ça va très bien…",
        "Où est la tête? À bientôt, très",
        "Pagó 5 € … “citado” – fin.",
    ],
)
def test_short_windows_1252_text(tmp_path, sample):
    assert read_back(tmp_path, sample.encode("cp1252")) == sample


def test_other_alphabets_are_left_to_the_detector(tmp_path):
    russian = "Привет, как дела? Всё хорошо, спасибо. Сегодня хорошая погода."
    assert read_back(tmp_path, russian.encode("cp1251")) == russian
    for sample, encoding in (("Καλημέρα κόσμε, τι κάνεις;", "cp1253"), ("Zażółć gęślą jaźń. Łódź.", "cp1250")):
        assert text._western(sample.encode(encoding)) is None


def test_utf16_guesses_need_nul_bytes(tmp_path, monkeypatch):
    class Match:
        def __init__(self, encoding: str, value: str):
            self.encoding, self.value = encoding, value

        def __str__(self) -> str:
            return self.value

    guesses = [Match("utf_16_be", "䍡曩"), Match("cp1251", "Сafé")]
    monkeypatch.setattr("charset_normalizer.from_bytes", lambda data: guesses)
    monkeypatch.setattr(text, "_western", lambda data: None)
    assert read_back(tmp_path, b"Caf\xe9") == "Сafé"
    assert read_back(tmp_path, b"C\x00a\x00f\x00\xe9") == "䍡曩"  # NUL bytes: UTF-16 is plausible


@pytest.mark.parametrize(
    "data",
    [
        "Café\r\nZoë\rFin\n".encode("cp1252"),
        "Café\r\nZoë\rFin\n".encode(),
        "﻿Café\r\nZoë\rFin\n".encode(),
        "﻿Café\r\nZoë\rFin\n".encode("utf-16-le"),
        "﻿Café\r\nZoë\rFin\n".encode("utf-16-be"),
        "﻿Café\r\nZoë\rFin\n".encode("utf-32-le"),
    ],
)
def test_encodings_and_line_ends(tmp_path, data):
    assert read_back(tmp_path, data) == "Café\nZoë\nFin\n"


# text written for other programs or as the result --------------------------------------------


def test_crlf_text_and_code_keep_single_line_ends(samples, convert, windows_newlines):
    notes = samples / "notes.txt"
    notes.write_bytes(b"line one\r\nline two\r\n\r\nline three\r\n")
    assert b"\r" not in convert(notes, "html").read_bytes()
    script = samples / "script.py"
    script.write_bytes(b"import os\r\nprint(os.name)\r\n")
    assert convert(script, "txt").read_bytes() == b"import os\nprint(os.name)\n"
    assert b"\r" not in convert(script, "md").read_bytes()


def test_typst_reads_text_with_unix_line_ends(samples, convert, windows_newlines, monkeypatch):
    seen = {}

    def fake_compile(main: Path, dst: Path, root: Path) -> Path:
        seen["content"] = (root / "content.txt").read_bytes()
        dst.write_bytes(b"%PDF-1.7\n")
        return dst

    monkeypatch.setattr(text, "typst_compile", fake_compile)
    notes = samples / "notes.txt"
    notes.write_bytes("line one\r\nline two ñ\r\n".encode("cp1252"))
    convert(notes, "pdf")
    assert seen["content"] == "line one\nline two ñ\n".encode()


# LibreOffice -------------------------------------------------------------------------------


def test_workbooks_reach_csv_through_the_data_converter():
    office = LibreOfficeConverter().edges()
    assert not [e for e in office if e.dst == "csv"]
    routes = plan("ods", [*office, *DataConverter().edges()])
    assert [(e.src, e.dst) for e in routes["csv"].edges] == [("ods", "xlsx"), ("xlsx", "csv")]
    assert isinstance(routes["csv"].edges[-1].converter, DataConverter)


def test_drawings_reach_png_through_pdf_pages():
    office = LibreOfficeConverter().edges()
    assert not [e for e in office if e.dst == "png"]
    route = plan("odg", [*office, *PdfConverter().edges()])["png"]
    assert [(e.src, e.dst) for e in route.edges] == [("odg", "pdf"), ("pdf", "png")]


def odf_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        content = zf.read("content.xml").decode("utf-8")
    return re.findall(r"<text:p[^>]*>([^<]*)</text:p>", content)


@needs_libreoffice
def test_libreoffice_imports_windows_1252_csv(samples, convert):
    src = samples / "ventas.csv"
    src.write_bytes("Nombre;Ciudad\r\nJosé Muñoz;Málaga\r\nZoë;Köln\r\n".encode("cp1252"))
    cells = odf_paragraphs(convert(src, "ods"))
    assert ["José Muñoz", "Málaga", "Zoë", "Köln"] == cells[2:]


@needs_libreoffice
def test_libreoffice_imports_crlf_text(samples, convert):
    src = samples / "notes.txt"
    src.write_bytes("línea uno\r\nlínea dos\r\n".encode("cp1252"))
    odt = convert(src, "odt")
    with zipfile.ZipFile(odt) as zf:
        assert b"&#x0d;" not in zf.read("content.xml")
    assert odf_paragraphs(odt)[:2] == ["línea uno", "línea dos"]


# pandoc ------------------------------------------------------------------------------------


def embedded_images(html: str) -> list[bytes]:
    return [base64.b64decode(data) for data in re.findall(r"data:image/png;base64,([A-Za-z0-9+/=]+)", html)]


@needs_pandoc
def test_pandoc_reads_windows_1252_markdown(samples, convert):
    src = samples / "notas.md"
    src.write_bytes("Pagó 5 € … “citado” – fin.\r\n".encode("cp1252"))
    assert "Pagó 5 € … “citado” – fin." in convert(src, "html").read_text(encoding="utf-8")


@needs_pandoc
def test_pandoc_finds_images_in_a_folder_named_with_the_path_separator(samples, convert):
    folder = samples / f"Informe 10{os.pathsep}12"
    folder.mkdir()
    logo = make_png(folder / "logo.png")
    src = folder / "notas.md"
    src.write_bytes("Logo de la empresa: ![logo](logo.png)\n".encode("cp1252"))  # read from a UTF-8 copy
    with zipfile.ZipFile(convert(src, "docx")) as zf:
        media = [zf.read(name) for name in zf.namelist() if name.startswith("word/media/")]
    assert media == [logo.read_bytes()]
    assert logo.exists()  # the link to the folder was removed, not the folder


@pytest.fixture
def untrusted(samples) -> tuple[Path, bytes, bytes]:
    """A folder with an image of its own and, outside it, a private file the document points at."""
    private = samples / "private"
    private.mkdir()
    secret = make_png(private / "secret.png", size=(30, 20)).read_bytes()
    (private / "notes.css").write_text("/* PRIVATE-NOTES */", encoding="utf-8")
    folder = samples / "download"
    folder.mkdir()
    own = make_png(folder / "own.png").read_bytes()
    return folder, secret, own


@needs_pandoc
def test_pandoc_does_not_embed_files_outside_the_document_folder(untrusted, convert):
    folder, secret, own = untrusted
    absolute = (folder.parent / "private" / "secret.png").resolve()
    src = folder / "invoice.md"
    src.write_text(
        f"---\ncss: {absolute.with_name('notes.css').as_posix()}\n---\n\n"
        f"![a]({absolute.as_posix()}) ![b]({absolute.as_uri()}) ![c](../private/secret.png) ![d](%2E%2E/private/secret.png)\n\n"
        f'<img src="{absolute.as_posix()}"> <img alt="x>y" src=../private/secret.png>\n\n'
        f"<div style=\"background: url('{absolute.as_posix()}')\">x</div>\n\n"
        f'<p style="background: url(&quot;{absolute.as_posix()}&quot;)">y</p>\n\n'
        f"<style>p {{ background: URL( '{absolute.as_posix()}' ) }}</style>\n\n"
        '![own](own.png) <img src="own.png">\n',
        encoding="utf-8",
    )
    html = convert(src, "html").read_text(encoding="utf-8")
    images = embedded_images(html)
    assert secret not in images and "PRIVATE-NOTES" not in html
    assert images.count(own) == 2
    assert 'href="../private/secret.png"' in html  # left as a plain link


@needs_pandoc
def test_pandoc_html_to_docx_keeps_private_files_out(untrusted, convert):
    folder, secret, own = untrusted
    absolute = (folder.parent / "private" / "secret.png").resolve()
    src = folder / "page.html"
    src.write_text(f'<html><body><p>Hola</p><img src="{absolute.as_posix()}"><img src="own.png"></body></html>')
    with zipfile.ZipFile(convert(src, "docx")) as zf:
        media = [zf.read(name) for name in zf.namelist() if name.startswith("word/media/")]
    assert media == [own]


def test_lua_filter_is_shipped_with_the_package():
    assert documents.SAFE_FILTER.is_file()


@needs_pandoc
@pytest.mark.parametrize(
    ("target", "kept"),
    [
        ("pics/a.png", True),
        ("pics/../a.png", True),
        ("a.png?x=../../../b", True),
        ("https://example.com/a.png", True),
        ("data:image/png;base64,iVBORw0KGgo=", True),
        ("/home/ana/.ssh/id_rsa", False),
        ("file:///etc/passwd", False),
        ("C:/Users/ana/secret.png", False),
        ("//server/share/secret.png", False),
        ("pics/../../secret.png", False),
        ("%2E%2E/secret.png", False),
    ],
)
def test_lua_filter_targets(tmp_path, target, kept):
    src = tmp_path / "doc.md"
    src.write_text(f'![img]({target}) <img src="{target}"> <img srcset="a.png 1x, {target} 2x">\n', encoding="utf-8")
    cmd = [tools.pandoc(), str(src), "-t", "html5", f"--lua-filter={documents.SAFE_FILTER}"]
    html = tools.run(cmd, cwd=tmp_path).stdout  # without --embed-resources nothing is fetched
    escaped = target.replace("&", "&amp;")
    assert (f'src="{escaped}"' in html) is kept
    assert (f"{escaped} 2x" in html) is kept
    assert f'href="{escaped}"' in html or kept  # the image became a plain link


# include directives -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, body",
    [
        ("abs.rst", "Title\n=====\n\n.. include:: {secret}\n"),
        ("rel.rst", "Title\n=====\n\n.. include:: ../secret/id_rsa\n"),
        ("a.org", '#+TITLE: x\n#+INCLUDE: "{secret}"\n'),
        ("a.adoc", "= T\n\ninclude::../secret/id_rsa[]\n"),
        ("a.tex", "\\documentclass{{article}}\\begin{{document}}\\input{{{secret}}}\\end{{document}}\n"),
    ],
)
def test_includes_from_outside_the_folder_are_refused(tmp_path, name, body):
    from transcript.cli import main

    secret = tmp_path / "secret" / "id_rsa"
    secret.parent.mkdir()
    secret.write_text("PLANTED-SECRET")
    folder = tmp_path / "doc"
    folder.mkdir()
    src = folder / name
    src.write_text(body.format(secret=secret.as_posix()), encoding="utf-8")
    out = tmp_path / "out"
    assert main([str(src), "--to", "html", "-o", str(out)]) == 1
    assert not any("PLANTED" in p.read_text(errors="ignore") for p in out.rglob("*") if p.is_file())


def test_relative_include_still_works_in_a_non_utf8_file(samples, convert):
    (samples / "part.rst").write_text("Included part text\n", encoding="utf-8")
    src = samples / "latin.rst"
    src.write_bytes("Café ok\n\n.. include:: part.rst\n".encode("cp1252"))
    assert "Included part text" in convert(src, "html").read_text(encoding="utf-8")
