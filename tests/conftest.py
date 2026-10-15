from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from transcript import tools
from transcript.cli import main


@pytest.fixture(autouse=True)
def english_and_private_tmp(monkeypatch, tmp_path):
    """English messages, and a private base folder for the temporary workspaces."""
    monkeypatch.setattr("transcript.i18n.LANG", "en")
    workspaces = tmp_path / "_workspaces"
    monkeypatch.setenv("TRANSCRIPT_TMPDIR", str(workspaces))
    yield
    leftovers = list(workspaces.iterdir()) if workspaces.exists() else []
    assert leftovers == [], f"temporary folders were not removed: {leftovers}"


@pytest.fixture
def convert(tmp_path):
    """Run ``transcript FILE --to TARGET`` and return the produced path."""

    def run(src: Path, target: str, *extra: str) -> Path:
        out = tmp_path / "out"
        before = set(out.iterdir()) if out.exists() else set()
        code = main([str(src), "--to", target, "-o", str(out), *extra])
        assert code == 0, f"{src.name} -> {target} failed with exit code {code}"
        produced = sorted(set(out.iterdir()) - before)
        assert produced, "nothing was produced"
        return produced[0]

    return run


@pytest.fixture
def samples(tmp_path) -> Path:
    folder = tmp_path / "samples"
    folder.mkdir()
    return folder


def make_png(path: Path, size=(64, 48), alpha=True) -> Path:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA" if alpha else "RGB", size, (0, 0, 0, 0) if alpha else (255, 255, 255))
    ImageDraw.Draw(img).ellipse((4, 4, size[0] - 4, size[1] - 4), fill=(200, 30, 30, 255))
    img.save(path)
    return path


def make_gif(path: Path) -> Path:
    from PIL import Image

    frames = [Image.new("RGB", (40, 30), color) for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=150, loop=0)
    return path


def make_pdf(path: Path, pages: int = 2) -> Path:
    import typst

    source = path.with_suffix(".typ")
    body = "\n#pagebreak()\n".join(f"= Página {n}\nTexto de prueba número {n}." for n in range(1, pages + 1))
    source.write_text('#set page(paper: "a6")\n' + body, encoding="utf-8")
    typst.compile(str(source), output=str(path))
    source.unlink()
    return path


def make_font(path: Path) -> Path:
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    def box():
        pen = TTGlyphPen(None)
        pen.moveTo((100, 0))
        pen.lineTo((100, 700))
        pen.lineTo((500, 700))
        pen.lineTo((500, 0))
        pen.closePath()
        return pen.glyph()

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "A"])
    builder.setupCharacterMap({ord("A"): "A"})
    builder.setupGlyf({".notdef": box(), "A": box()})
    builder.setupHorizontalMetrics({".notdef": (600, 100), "A": (600, 100)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    builder.save(str(path))
    return path


def make_media(path: Path, video: bool = True, seconds: int = 1) -> Path:
    ffmpeg = tools.ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg is not available")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if video:
        cmd += ["-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=96x64:rate=10"]
    cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if video:
        cmd += ["-pix_fmt", "yuv420p", "-shortest"]
    subprocess.run(cmd + [str(path)], check=True)
    return path
