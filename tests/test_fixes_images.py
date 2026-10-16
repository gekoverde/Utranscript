"""Regression tests for still/animated images, colour profiles, scanned PDFs and font outlines."""

from __future__ import annotations

import itertools
import struct

import pytest
from conftest import make_font, make_gif, make_png

from transcript.cli import main
from transcript.converters.base import ConversionError
from transcript.converters.fonts import FontConverter
from transcript.converters.images import pillow_formats, register_plugins
from transcript.converters.ocr import OcrConverter
from transcript.converters.pdf import PdfConverter
from transcript.engine import Context, Options, Reporter


def open_image(path):
    from PIL import Image

    register_plugins()
    return Image.open(path)


def frame_info(path, key: str) -> list:
    from PIL import ImageSequence

    values = []
    with open_image(path) as img:
        for frame in ImageSequence.Iterator(img):
            frame.load()
            values.append(frame.info.get(key))
    return values


def needs(feature: str):
    from PIL import features

    return pytest.mark.skipif(not features.check(feature), reason=f"Pillow was built without {feature}")


def pdf_pages(path) -> int:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def run_cli(src, target: str, out) -> tuple[int, list]:
    code = main([str(src), "--to", target, "-o", str(out)])
    return code, sorted(out.iterdir()) if out.exists() else []


# multi-frame stills ---------------------------------------------------------------------


def make_psd(path, size=(20, 10)):
    """A two-layer RGB PSD (red, half green) whose composite image is solid blue."""
    w, h = size
    n = w * h

    def record(right: int) -> bytes:
        rec = struct.pack(">4iH", 0, 0, h, right, 3)
        rec += b"".join(struct.pack(">hI", channel, h * right + 2) for channel in range(3))
        extra = struct.pack(">II", 0, 0) + b"\x01a\x00\x00"  # no mask, no blending ranges, name "a"
        return rec + b"8BIMnorm" + bytes([255, 0, 0, 0]) + struct.pack(">I", len(extra)) + extra

    def planes(right: int, rgb) -> bytes:
        return b"".join(b"\x00\x00" + bytes([value]) * (h * right) for value in rgb)

    layers = struct.pack(">h", 2) + record(w) + record(w // 2) + planes(w, (255, 0, 0)) + planes(w // 2, (0, 255, 0))
    section = struct.pack(">I", len(layers)) + layers + struct.pack(">I", 0)
    header = b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3) + struct.pack(">II", 0, 0)
    composite = b"\x00\x00" + bytes(n) + bytes(n) + b"\xff" * n
    path.write_bytes(header + struct.pack(">I", len(section)) + section + composite)
    return path


def make_mpo(path):
    """A stereo MPO (two pictures) whose EXIF says it must be rotated 90 degrees."""
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = 6
    frames = [Image.new("RGB", (60, 40), color) for color in ((255, 0, 0), (0, 0, 255))]
    frames[0].save(path, "MPO", save_all=True, append_images=frames[1:], exif=exif)
    return path


def make_tiff_pages(path, pages: int = 3):
    from PIL import Image

    frames = [Image.new("RGB", (40, 30), (40 * i, 0, 0)) for i in range(pages)]
    frames[0].save(path, save_all=True, append_images=frames[1:])
    return path


@pytest.mark.parametrize("target", ["png", "gif", "tiff"])
def test_layered_psd_becomes_its_flattened_composite(samples, convert, target):
    psd = make_psd(samples / "layers.psd")
    with open_image(psd) as img:
        assert img.format == "PSD" and img.is_animated  # what made it look like an animation
    with open_image(convert(psd, target)) as img:
        assert getattr(img, "n_frames", 1) == 1
        assert img.convert("RGB").getpixel((15, 5)) == (0, 0, 255)


@pytest.mark.parametrize("target", ["png", "gif", "webp"])
def test_mpo_becomes_its_primary_picture_upright(samples, convert, target):
    with open_image(convert(make_mpo(samples / "stereo.jpg"), target)) as img:
        assert getattr(img, "n_frames", 1) == 1
        assert img.size == (40, 60)
        r, g, b = img.convert("RGB").getpixel((20, 30))
        assert r > 200 and b < 50


def test_mpo_to_pdf_is_one_page(samples, convert):
    assert pdf_pages(convert(make_mpo(samples / "stereo.jpg"), "pdf")) == 1


def test_multipage_tiff_is_a_still_in_raster_formats(samples, convert):
    tiff = make_tiff_pages(samples / "scan.tiff")
    for target in ("png", "gif"):
        with open_image(convert(tiff, target)) as img:
            assert getattr(img, "n_frames", 1) == 1
    assert pdf_pages(convert(tiff, "pdf")) == 3


def test_animation_to_tiff_keeps_every_frame(samples, convert):
    with open_image(convert(make_gif(samples / "anim.gif"), "tiff")) as img:
        assert img.n_frames == 3


# animation timing and looping -----------------------------------------------------------


def make_animation(path, fmt: str, durations=(100, 500, 1000), loop: int | None = 0):
    from PIL import Image

    frames = [Image.new("RGB", (40, 30), color) for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    params = {"duration": list(durations)} | ({} if loop is None else {"loop": loop})
    frames[0].save(path, fmt, save_all=True, append_images=frames[1:], **params)
    return path


@needs("webp")
@pytest.mark.parametrize("target", ["gif", "png"])
def test_per_frame_durations_survive(samples, convert, target):
    webp = make_animation(samples / "anim.webp", "WEBP")
    assert frame_info(convert(webp, target), "duration") == [100, 500, 1000]


@needs("webp")
@pytest.mark.parametrize("target", ["webp", "png"])
def test_gif_that_plays_once_does_not_start_looping(samples, convert, target):
    gif = make_animation(samples / "once.gif", "GIF", loop=None)
    with open_image(gif) as img:
        assert "loop" not in img.info
    with open_image(convert(gif, target)) as img:
        assert img.info.get("loop") == 1


@needs("webp")
@pytest.mark.parametrize(
    ("name", "loop", "target", "expected"),
    [("forever.gif", 0, "webp", 0), ("thrice.gif", 2, "webp", 3), ("thrice.webp", 3, "gif", 2), ("once.webp", 1, "gif", None)],
)
def test_loop_counts_are_translated(samples, convert, name, loop, target, expected):
    # A GIF loop count is the number of repeats after the first play; WebP and APNG count plays.
    src = make_animation(samples / name, "GIF" if name.endswith(".gif") else "WEBP", loop=loop)
    with open_image(convert(src, target)) as img:
        assert img.info.get("loop") == expected


# transparency, colour, pixel modes ------------------------------------------------------


def make_palette_png(path):
    from PIL import Image, ImageDraw

    img = Image.new("P", (40, 30), 0)
    img.putpalette([0, 0, 0, 200, 30, 30])
    ImageDraw.Draw(img).rectangle((10, 8, 30, 22), fill=1)
    img.save(path, transparency=0)
    return path


@pytest.mark.parametrize("target", ["tiff", "tga"])
def test_palette_transparency_is_kept(samples, convert, target):
    with open_image(convert(make_palette_png(samples / "logo.png"), target)) as img:
        rgba = img.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0
        assert rgba.getpixel((20, 15)) == (200, 30, 30, 255)


def cyan_prints_red_profile() -> bytes:
    """A minimal CMYK ICC profile in which pure cyan is red, to prove that the profile is used."""
    corners = []  # CMYK -> 8-bit Lab at the 16 corners of the colour cube
    for c, m, y, k in itertools.product((0, 1), repeat=4):
        if k:
            corners.append((0, 128, 128))
        elif (c, m, y) == (1, 0, 0):
            corners.append((136, 208, 195))
        else:
            corners.append((255, 128, 128) if (c, m, y) == (0, 0, 0) else (128, 128, 128))
    lut = b"mft1" + bytes(4) + bytes([4, 3, 2, 0])
    lut += b"".join(struct.pack(">i", 65536 if i % 4 == 0 else 0) for i in range(9))
    lut += bytes(range(256)) * 4 + bytes(v for corner in corners for v in corner) + bytes(range(256)) * 3
    white = b"XYZ " + bytes(4) + struct.pack(">3i", 63190, 65536, 54061)
    tags = [(b"A2B0", lut), (b"wtpt", white)]
    offset = 128 + 4 + 12 * len(tags)
    table, data = struct.pack(">I", len(tags)), b""
    for signature, body in tags:
        table += signature + struct.pack(">II", offset + len(data), len(body))
        data += body + bytes(-len(body) % 4)
    header = struct.pack(">I4sI4s4s4s12s4s", offset + len(data), b"", 0x02100000, b"prtr", b"CMYK", b"Lab ", b"", b"acsp")
    header += bytes(24) + struct.pack(">I3i", 0, 63190, 65536, 54061)
    return header + bytes(128 - len(header)) + table + data


def make_cmyk(path, fmt: str):
    from PIL import Image

    Image.new("CMYK", (32, 24), (255, 0, 0, 0)).save(path, fmt, icc_profile=cyan_prints_red_profile())
    return path


@needs("littlecms2")
@pytest.mark.parametrize(("source", "fmt", "target"), [("photo.jpg", "JPEG", "png"), ("photo.tiff", "TIFF", "jpg")])
def test_cmyk_is_colour_managed_to_rgb(samples, convert, source, fmt, target):
    with open_image(convert(make_cmyk(samples / source, fmt), target)) as img:
        assert img.mode == "RGB"
        r, g, b = img.getpixel((5, 5))
        assert r > 200 and g < 60 and b < 60  # red as the profile says, not the naive cyan
        assert img.info.get("icc_profile", b"")[16:20] in (b"", b"RGB ")


def test_cmyk_profile_never_lands_on_rgb_pixels(samples, convert):
    with open_image(convert(make_cmyk(samples / "photo.jpg", "JPEG"), "webp")) as img:
        assert img.info.get("icc_profile", b"")[16:20] in (b"", b"RGB ")


def test_cmyk_tiff_keeps_its_profile(samples, convert):
    with open_image(convert(make_cmyk(samples / "photo.jpg", "JPEG"), "tiff")) as img:
        assert img.mode == "CMYK"
        assert img.info["icc_profile"][16:20] == b"CMYK"


@pytest.mark.parametrize("mode", ["L", "I;16", "1", "LA"])
def test_qoi_accepts_any_pixel_mode(samples, convert, mode):
    from PIL import Image

    if "qoi" not in pillow_formats()[1]:
        pytest.skip("this Pillow cannot write QOI")
    src = samples / "gray.png"
    Image.new(mode, (20, 10)).save(src)
    with open_image(convert(src, "qoi")) as img:
        assert img.mode in ("RGB", "RGBA") and img.size == (20, 10)


def test_png_alpha_still_reaches_qoi(samples, convert):
    if "qoi" not in pillow_formats()[1]:
        pytest.skip("this Pillow cannot write QOI")
    with open_image(convert(make_png(samples / "logo.png"), "qoi")) as img:
        assert img.mode == "RGBA" and img.getpixel((0, 0))[3] == 0


# scanned PDF ----------------------------------------------------------------------------


def make_scanned_pdf(path):
    from PIL import Image

    Image.new("RGB", (200, 120), "white").save(path, "PDF")
    return path


def context(tmp_path) -> Context:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return Context(workspace, Options(dpi=72), Reporter())


def pdf_to_txt_edge():
    return next(e for e in PdfConverter().edges() if e.dst == "txt")


def test_scanned_pdf_without_tesseract_explains_why(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(OcrConverter, "available", lambda self: False)
    dst = tmp_path / "scan.txt"
    with pytest.raises(ConversionError, match="Tesseract"):
        PdfConverter().convert(make_scanned_pdf(samples / "scan.pdf"), dst, pdf_to_txt_edge(), context(tmp_path))
    assert not dst.exists()


def test_scanned_pdf_where_ocr_finds_nothing(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(OcrConverter, "available", lambda self: True)
    monkeypatch.setattr(OcrConverter, "read_image", lambda self, image, ctx: "  \n")
    dst = tmp_path / "scan.txt"
    with pytest.raises(ConversionError, match="OCR"):
        PdfConverter().convert(make_scanned_pdf(samples / "scan.pdf"), dst, pdf_to_txt_edge(), context(tmp_path))
    assert not dst.exists()


def test_scanned_pdf_to_txt_fails_instead_of_saving_an_empty_file(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(OcrConverter, "available", lambda self: False)
    code, produced = run_cli(make_scanned_pdf(samples / "scan.pdf"), "txt", tmp_path / "out")
    assert code != 0 and produced == []


# fonts ----------------------------------------------------------------------------------


def make_cff_font(path, flavor: str | None = None):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    def box():
        pen = T2CharStringPen(600, None)
        pen.moveTo((100, 0))
        pen.lineTo((100, 700))
        pen.lineTo((500, 700))
        pen.lineTo((500, 0))
        pen.closePath()
        return pen.getCharString()

    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "A"])
    builder.setupCharacterMap({ord("A"): "A"})
    builder.setupCFF("Test-Regular", {"FullName": "Test"}, {".notdef": box(), "A": box()}, {})
    builder.setupHorizontalMetrics({".notdef": (600, 100), "A": (600, 100)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    builder.font.flavor = flavor
    builder.save(str(path))
    return path


def make_tt_font(path, flavor: str):
    from fontTools.ttLib import TTFont

    with TTFont(str(make_font(path.with_suffix(".ttf")))) as font:
        font.flavor = flavor
        font.save(str(path))
    return path


def font_edge(src: str, dst: str):
    return next(e for e in FontConverter().edges() if (e.src, e.dst) == (src, dst))


@pytest.mark.parametrize("flavor", ["woff", "woff2"])
def test_font_outlines_are_checked_in_every_step(samples, tmp_path, flavor):
    if flavor == "woff2":
        pytest.importorskip("brotli")
    cff = make_cff_font(samples / f"cff.{flavor}", flavor)
    tt = make_tt_font(samples / f"tt.{flavor}", flavor)
    with pytest.raises(ConversionError, match="CFF"):
        FontConverter().convert(cff, tmp_path / "cff.ttf", font_edge(flavor, "ttf"), None)
    with pytest.raises(ConversionError, match="TrueType"):
        FontConverter().convert(tt, tmp_path / "tt.otf", font_edge(flavor, "otf"), None)
    assert not (tmp_path / "cff.ttf").exists() and not (tmp_path / "tt.otf").exists()
    otf = FontConverter().convert(cff, tmp_path / "cff.otf", font_edge(flavor, "otf"), None)
    assert otf.read_bytes()[:4] == b"OTTO"


def test_cff_web_font_never_becomes_a_ttf(samples, tmp_path):
    code, produced = run_cli(make_cff_font(samples / "cff.woff", "woff"), "ttf", tmp_path / "out")
    assert code != 0 and produced == []
