"""End to end conversions through the command line (``transcript FILE --to FORMAT``)."""

import json
import zipfile

import pytest
from conftest import make_font, make_gif, make_media, make_pdf, make_png

from transcript import formats, tools
from transcript.converters.images import register_plugins

needs_libreoffice = pytest.mark.skipif(tools.soffice() is None, reason="LibreOffice is not installed")


def open_image(path):
    from PIL import Image

    register_plugins()
    return Image.open(path)


# images --------------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["jpg", "webp", "bmp", "tiff", "gif", "avif", "heic", "tga", "qoi"])
def test_png_to_images(samples, convert, target):
    result = convert(make_png(samples / "logo.png"), target)
    assert result.suffix == formats.get(target).ext
    with open_image(result) as img:
        assert img.size == (64, 48)


def test_transparency_is_flattened_on_white_for_jpeg(samples, convert):
    result = convert(make_png(samples / "logo.png"), "jpg")
    with open_image(result) as img:
        assert img.mode == "RGB"
        assert min(img.getpixel((0, 0))) >= 250  # white, give or take JPEG noise


def test_icons_are_square(samples, convert):
    result = convert(make_png(samples / "logo.png", size=(200, 120)), "ico")
    with open_image(result) as img:
        assert img.size[0] == img.size[1] == 128


def test_animation_is_kept(samples, convert):
    gif = make_gif(samples / "anim.gif")
    for target in ("webp", "png"):
        with open_image(convert(gif, target)) as img:
            assert getattr(img, "n_frames", 1) == 3


def test_image_to_pdf(samples, convert):
    result = convert(make_png(samples / "logo.png"), "pdf")
    assert result.read_bytes().startswith(b"%PDF")


# PDF -----------------------------------------------------------------------------------


def test_pdf_to_text(samples, convert):
    text = convert(make_pdf(samples / "doc.pdf"), "txt").read_text(encoding="utf-8")
    assert "Página 1" in text and "número 2" in text


def test_pdf_pages_to_images(samples, convert):
    result = convert(make_pdf(samples / "doc.pdf", pages=3), "png")
    assert result.is_dir()
    assert sorted(p.name for p in result.iterdir()) == ["doc-001.png", "doc-002.png", "doc-003.png"]


def test_single_page_pdf_to_one_image(samples, convert):
    result = convert(make_pdf(samples / "doc.pdf", pages=1), "jpg")
    assert result.name == "doc.jpg"


def test_pdf_to_multipage_tiff(samples, convert):
    with open_image(convert(make_pdf(samples / "doc.pdf", pages=2), "tiff")) as img:
        assert img.n_frames == 2


def test_comic_book_round_trip(samples, convert):
    cbz = convert(make_pdf(samples / "doc.pdf", pages=2), "cbz")
    with zipfile.ZipFile(cbz) as zf:
        assert len(zf.namelist()) == 2
    cbz_copy = samples / "comic.cbz"
    cbz_copy.write_bytes(cbz.read_bytes())
    assert convert(cbz_copy, "pdf").read_bytes().startswith(b"%PDF")


# text and documents ----------------------------------------------------------------------


def test_text_to_pdf_and_html(samples, convert):
    src = samples / "nota.txt"
    src.write_bytes("Línea con acentos: áéíóú ñ\n<b>no es html</b>\n".encode("cp1252"))
    html = convert(src, "html").read_text(encoding="utf-8")
    assert "áéíóú" in html and "&lt;b&gt;" in html
    assert convert(src, "pdf").read_bytes().startswith(b"%PDF")


def test_code_conversions(samples, convert):
    src = samples / "script.py"
    src.write_text("def f(x):\n    return x * 2\n")
    assert "```py" in convert(src, "md").read_text()
    assert "<html" in convert(src, "html").read_text(encoding="utf-8")
    assert convert(src, "pdf").read_bytes().startswith(b"%PDF")


@pytest.fixture
def markdown(samples):
    src = samples / "doc.md"
    src.write_text(
        "# Título\n\nUn **documento** con acentos: ñ.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    return src


@pytest.mark.parametrize("target", ["docx", "odt", "html", "epub", "rst", "tex", "txt", "pdf"])
def test_markdown(markdown, convert, target):
    result = convert(markdown, target)
    assert result.stat().st_size > 0
    if target == "html":
        assert "Título" in result.read_text(encoding="utf-8")


def test_markdown_to_pdf_text_is_searchable(markdown, convert, samples):
    pdf = convert(markdown, "pdf")
    copy = samples / "copy.pdf"
    copy.write_bytes(pdf.read_bytes())
    assert "documento" in convert(copy, "txt").read_text(encoding="utf-8")


def test_docx_round_trip(markdown, convert, samples):
    docx = convert(markdown, "docx")
    copy = samples / "copy.docx"
    copy.write_bytes(docx.read_bytes())
    assert "Título" in convert(copy, "md").read_text(encoding="utf-8")


@needs_libreoffice
def test_libreoffice_docx_to_pdf(markdown, convert, samples):
    docx = convert(markdown, "docx")
    copy = samples / "informe.docx"
    copy.write_bytes(docx.read_bytes())
    assert convert(copy, "pdf").read_bytes().startswith(b"%PDF")


# data ------------------------------------------------------------------------------------


@pytest.fixture
def csv_file(samples):
    src = samples / "datos.csv"
    src.write_text("nombre;edad;cp\nAna;30;01234\nLuis;25;28001\n", encoding="utf-8")
    return src


def test_csv_to_json_detects_separator_and_types(csv_file, convert):
    data = json.loads(convert(csv_file, "json").read_text(encoding="utf-8"))
    assert data == [{"nombre": "Ana", "edad": 30, "cp": "01234"}, {"nombre": "Luis", "edad": 25, "cp": "28001"}]


@pytest.mark.parametrize("target", ["yaml", "toml", "xml", "plist", "jsonl", "tsv", "xlsx", "html", "docx"])
def test_csv_to_everything(csv_file, convert, target):
    assert convert(csv_file, target).stat().st_size > 0


def test_xlsx_with_several_sheets(samples, convert):
    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.active.title = "Ventas"
    workbook.active.append(["mes", "total"])
    workbook.active.append(["enero", 100])
    other = workbook.create_sheet("Gastos")
    other.append(["concepto", "importe"])
    other.append(["luz", 50])
    workbook.save(samples / "libro.xlsx")

    folder = convert(samples / "libro.xlsx", "csv")
    assert sorted(p.name for p in folder.iterdir()) == ["Gastos.csv", "Ventas.csv"]
    data = json.loads(convert(samples / "libro.xlsx", "json").read_text(encoding="utf-8"))
    assert data == {"Ventas": [{"mes": "enero", "total": 100}], "Gastos": [{"concepto": "luz", "importe": 50}]}
    page = convert(samples / "libro.xlsx", "html").read_text(encoding="utf-8")
    assert "<h2>Gastos</h2>" in page and "<td>enero</td>" in page
    assert convert(samples / "libro.xlsx", "pdf").read_bytes().startswith(b"%PDF")


def test_json_tree_formats(samples, convert):
    src = samples / "conf.json"
    src.write_text(json.dumps({"app": {"name": "demo", "tags": ["a", "b"], "on": True, "none": None}}))
    assert 'name = "demo"' in convert(src, "toml").read_text()
    assert "<name>demo</name>" in convert(src, "xml").read_text()
    assert "name: demo" in convert(src, "yaml").read_text()
    assert "[app]" in convert(src, "ini").read_text()


# subtitles, fonts, archives --------------------------------------------------------------


def test_subtitles(samples, convert):
    src = samples / "subs.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,500\nHola <i>mundo</i>\n\n2\n00:00:03,000 --> 00:00:04,000\nAdiós\n")
    assert convert(src, "vtt").read_text(encoding="utf-8").startswith("WEBVTT")
    assert "Dialogue:" in convert(src, "ass").read_text(encoding="utf-8")
    assert convert(src, "txt").read_text(encoding="utf-8") == "Hola mundo\nAdiós\n"


def test_fonts(samples, convert):
    from fontTools.ttLib import TTFont

    woff2 = convert(make_font(samples / "test.ttf"), "woff2")
    with TTFont(str(woff2)) as font:
        assert font.flavor == "woff2"
    copy = samples / "copy.woff2"
    copy.write_bytes(woff2.read_bytes())
    assert convert(copy, "ttf").read_bytes()[:4] == b"\x00\x01\x00\x00"


def test_folder_and_archives(samples, convert, tmp_path):
    folder = samples / "proyecto"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("a")
    (folder / "sub" / "b.txt").write_text("b")

    archive = convert(folder, "zip")
    with zipfile.ZipFile(archive) as zf:
        assert "proyecto/sub/b.txt" in zf.namelist()
    for target in ("7z", "tgz", "tbz2", "txz", "tar"):
        assert convert(archive, target).stat().st_size > 0
    extracted = convert(archive, "folder")
    assert (extracted / "proyecto" / "sub" / "b.txt").read_text() == "b"


def test_zip_slip_is_refused(samples, tmp_path):
    from transcript.cli import main

    evil = samples / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escaped.txt", "nope")
    assert main([str(evil), "--to", "folder", "-o", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "escaped.txt").exists()


# audio and video ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["mp3", "flac", "ogg", "opus", "m4a"])
def test_audio(samples, convert, target):
    assert convert(make_media(samples / "tone.wav", video=False), target).stat().st_size > 0


def test_video(samples, convert):
    video = make_media(samples / "clip.mp4")
    for target in ("mkv", "webm", "mp3", "gif"):
        assert convert(video, target).stat().st_size > 0


def test_gif_to_video(samples, convert):
    assert convert(make_gif(samples / "anim.gif"), "mp4").stat().st_size > 0


def test_speech_to_subtitles_with_a_fake_model(samples, convert, monkeypatch):
    """The real model is downloaded on first use; here faster_whisper is replaced by a stub."""
    import sys
    import types
    from collections import namedtuple

    Segment = namedtuple("Segment", "start end text")
    Info = namedtuple("Info", "duration")

    class FakeModel:
        def __init__(self, name, **kwargs):
            assert name == "tiny"

        def transcribe(self, path, **kwargs):
            return iter([Segment(0.0, 1.5, " Hola mundo"), Segment(1.5, 3.0, " Adiós")]), Info(3.0)

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    from transcript.converters import all_edges, converter_edges
    from transcript.converters.speech import SpeechConverter

    monkeypatch.setattr(SpeechConverter, "available", lambda self: True)
    converter_edges.cache_clear()
    all_edges.cache_clear()
    try:
        audio = make_media(samples / "voice.wav", video=False)
        srt = convert(audio, "srt", "--model", "tiny").read_text(encoding="utf-8")
        assert "00:00:01,500 --> 00:00:03,000" in srt and "Adiós" in srt
    finally:
        converter_edges.cache_clear()
        all_edges.cache_clear()
