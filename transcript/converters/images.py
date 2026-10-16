"""Images: Pillow for raster formats, plus SVG and camera RAW support."""

from __future__ import annotations

import importlib.util
import io
from functools import cache
from pathlib import Path

from .. import tools
from .base import ConversionError, Converter, Edge

# Our format id -> Pillow format name.
PILLOW_NAMES = {
    "png": "PNG",
    "jpg": "JPEG",
    "webp": "WEBP",
    "avif": "AVIF",
    "heic": "HEIF",
    "gif": "GIF",
    "bmp": "BMP",
    "tiff": "TIFF",
    "ico": "ICO",
    "icns": "ICNS",
    "psd": "PSD",
    "tga": "TGA",
    "jp2": "JPEG2000",
    "ppm": "PPM",
    "pcx": "PCX",
    "dds": "DDS",
    "qoi": "QOI",
}

ANIMATED = {"gif", "webp", "png", "avif"}
# Pillow also reports layered PSDs and stereo MPOs as "animated": only these really are.
ANIMATED_SOURCES = {"GIF", "PNG", "WEBP", "AVIF"}
NO_ALPHA = {"jpg", "bmp", "pcx", "ppm"}
SAVE_PARAMS = {
    "jpg": {"quality": 92, "optimize": True},
    "webp": {"quality": 90, "method": 4},
    "avif": {"quality": 80},
    "heic": {"quality": 90},
    "tiff": {"compression": "tiff_lzw"},
}
KEEPS_EXIF = {"jpg", "webp", "png", "avif", "heic"}
KEEPS_ICC = {"jpg", "webp", "png", "avif", "heic", "tiff"}
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


@cache
def register_plugins() -> None:
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        pass


@cache
def pillow_formats() -> tuple[frozenset[str], frozenset[str]]:
    """(readable, writable) format ids according to the installed Pillow build."""
    from PIL import Image

    register_plugins()
    Image.init()
    readable = frozenset(f for f, name in PILLOW_NAMES.items() if name in Image.OPEN)
    writable = frozenset(f for f, name in PILLOW_NAMES.items() if name in Image.SAVE)
    return readable, writable


def cmyk_to_rgb(img):
    """CMYK to sRGB through the embedded ICC profile when there is one (plain inversion otherwise)."""
    icc = img.info.get("icc_profile")
    if icc:
        try:
            from PIL import ImageCms

            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            rgb = ImageCms.profileToProfile(img, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
            rgb.info.pop("icc_profile", None)  # untagged means sRGB; lcms' own profile is v4, which old viewers mishandle
            return rgb
        except Exception:
            pass
    rgb = img.convert("RGB")
    rgb.info.pop("icc_profile", None)
    return rgb


def icc_fits(icc: bytes, mode: str) -> bool:
    """Whether an ICC profile is for this pixel mode's colour space (a CMYK profile on RGB pixels is invalid)."""
    expected = {"CMYK": b"CMYK", "L": b"GRAY", "LA": b"GRAY", "1": b"GRAY"}.get(mode, b"RGB ")
    return icc[16:20] == expected


def flatten(img, background=(255, 255, 255)):
    """Return an RGB/L copy of ``img`` with transparency composed over a white background."""
    from PIL import Image

    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        out = Image.new("RGB", rgba.size, background)
        out.paste(rgba, mask=rgba.getchannel("A"))
        return out
    if img.mode in ("RGB", "L"):
        return img
    return cmyk_to_rgb(img) if img.mode == "CMYK" else img.convert("RGB")


def to_8bit(img):
    if img.mode.startswith("I;16") or img.mode == "I":
        return img.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    if img.mode == "F":
        return img.convert("L")
    return img


def square(img):
    """Center the picture on a transparent square canvas (icons must be square)."""
    from PIL import Image

    if img.width == img.height:
        return img
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img.convert("RGBA"), ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def has_alpha(img) -> bool:
    return img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (img.mode == "P" and "transparency" in img.info)


def keeps_frames(im, target: str) -> bool:
    """Whether every frame is written: animations stay animations, multi-page TIFFs stay multi-page TIFFs."""
    if not getattr(im, "is_animated", False):
        return False
    if im.format in ANIMATED_SOURCES:
        return target in ANIMATED or target == "tiff"
    return im.format == "TIFF" and target == "tiff"


def plays(im) -> int:
    """How many times an animation plays, 0 meaning forever."""
    if im.format == "AVIF":  # Pillow does not read the AVIF repetition count; they usually loop
        return 0
    loop = im.info.get("loop")
    if loop is None:  # a GIF without a NETSCAPE loop block plays once
        return 1
    # A GIF loop count is the number of repeats after the first play (as in browsers and gif2webp).
    return loop + 1 if im.format == "GIF" and loop else loop


class PillowConverter(Converter):
    name = "Pillow"

    def details(self) -> str:
        import PIL

        readable, writable = pillow_formats()
        return f"Pillow {PIL.__version__} · {len(readable)} read / {len(writable)} write"

    def edges(self):
        readable, writable = pillow_formats()
        edges = self.matrix(sorted(readable), sorted(writable))
        # Images become one page PDFs (multi-page TIFFs become multi-page PDFs).
        edges += [self.edge(fmt, "pdf", terminal=True) for fmt in sorted(readable)]
        return edges

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

        register_plugins()
        try:
            im = Image.open(src)
        except (UnidentifiedImageError, OSError) as exc:
            raise ConversionError(f"cannot read the image: {exc}") from exc
        with im:
            if edge.dst == "pdf":
                pages = ImageSequence.Iterator(im) if im.format == "TIFF" else [im]
                images = [flatten(to_8bit(ImageOps.exif_transpose(p.copy()) or p)) for p in pages]
                dpi = (im.info.get("dpi") or (96, 96))[0] or 96
                images[0].save(dst, "PDF", save_all=True, append_images=images[1:], resolution=float(dpi))
                return dst

            target = edge.dst
            fmt = PILLOW_NAMES[target]
            if keeps_frames(im, target):
                images, durations = [], []
                for frame in ImageSequence.Iterator(im):
                    copy = frame.copy()  # loading the frame is what reads its own duration (WebP)
                    durations.append(copy.info.get("duration") or 100)
                    images.append(self._prepare(copy, target))
                params = {"save_all": True, "append_images": images[1:]}
                if target in ANIMATED:
                    params["duration"] = durations
                    loops = plays(im)
                    if target != "gif":
                        params["loop"] = loops
                    else:  # None (no loop block) plays once; it must be explicit or Pillow copies the source's
                        params["loop"] = None if loops == 1 else max(loops - 1, 0)
                self._save(images[0], dst, target, fmt, params)
                return dst

            # PSD: the flattened composite. MPO: the primary picture. Multi-page TIFF: the first page.
            img = ImageOps.exif_transpose(im) or im
            img = self._prepare(img, target)
            params = dict(SAVE_PARAMS.get(target, {}))
            icc = im.info.get("icc_profile")
            img.info.pop("icc_profile", None)  # PNG and TIFF would write it on their own
            if icc and target in KEEPS_ICC and icc_fits(icc, img.mode):
                params["icc_profile"] = icc
            exif = img.getexif()
            if exif and target in KEEPS_EXIF:
                params["exif"] = exif.tobytes()
            if target in ("ico", "icns"):
                img = square(img)
            if target == "ico":
                params["sizes"] = [(s, s) for s in ICO_SIZES if s <= img.width] or [img.size]
            self._save(img, dst, target, fmt, params)
        return dst

    @staticmethod
    def _prepare(img, target: str):
        img = to_8bit(img)
        if img.mode == "CMYK" and target != "tiff":
            img = cmyk_to_rgb(img)
        if target in NO_ALPHA:
            img = flatten(img)
        elif target == "ico" and img.mode != "RGBA":
            img = img.convert("RGBA")
        elif target == "qoi" and img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if has_alpha(img) else "RGB")
        elif img.mode == "P" and target != "gif" and (has_alpha(img) or target in ("png", "webp", "avif", "heic")):
            # Outside GIF, palette transparency only survives as a real alpha channel (TIFF, TGA...).
            img = img.convert("RGBA" if has_alpha(img) else "RGB")
        return img

    @staticmethod
    def _save(img, dst: Path, target: str, fmt: str, params: dict) -> None:
        try:
            img.save(dst, fmt, **params)
            return
        except Exception:
            pass
        # Some formats only accept a few pixel modes: retry with a universal one.
        params = {k: v for k, v in params.items() if k not in ("exif", "icc_profile")}
        fallback = img.convert("RGBA") if has_alpha(img) and target not in NO_ALPHA else flatten(img)
        if "append_images" in params:
            params["append_images"] = [
                f.convert("RGBA") if has_alpha(f) and target not in NO_ALPHA else flatten(f) for f in params["append_images"]
            ]
        try:
            fallback.save(dst, fmt, **params)
        except Exception as exc:
            raise ConversionError(f"Pillow cannot write {fmt}: {exc}") from exc


@cache
def svg_backend() -> str | None:
    try:
        import cairosvg  # noqa: F401  (fails if the cairo library is missing)

        return "cairosvg"
    except Exception:
        pass
    if tools.rsvg_convert():
        return "rsvg-convert"
    if tools.inkscape():
        return "inkscape"
    return None


class SvgConverter(Converter):
    """Vector SVG to PNG/PDF with the first renderer found."""

    name = "SVG renderer"
    hint = "pip install cairosvg  ·  or install librsvg (rsvg-convert) or Inkscape"

    @staticmethod
    def backend() -> str | None:
        return svg_backend()

    def available(self) -> bool:
        return self.backend() is not None

    def details(self) -> str:
        return self.backend() or ""

    def edges(self):
        return [self.edge("svg", "png"), self.edge("svg", "pdf", terminal=True)]

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        backend = self.backend()
        if backend == "cairosvg":
            import cairosvg

            render = cairosvg.svg2png if edge.dst == "png" else cairosvg.svg2pdf
            try:
                render(bytestring=src.read_bytes(), url=src.resolve().as_uri(), write_to=str(dst))
            except Exception as exc:
                raise ConversionError(f"cairosvg: {exc}") from exc
        elif backend == "rsvg-convert":
            ctx.run([tools.rsvg_convert(), "-f", edge.dst, "-o", str(dst), str(src)])
        else:
            ctx.run([tools.inkscape(), str(src), f"--export-filename={dst}"])
        return dst


class RawConverter(Converter):
    """Camera RAW photos (DNG, CR2, NEF, ARW...) through LibRaw."""

    name = "rawpy (LibRaw)"
    hint = "pip install rawpy  ·  or install transcript-cli[raw]"

    def available(self) -> bool:
        return importlib.util.find_spec("rawpy") is not None

    def edges(self):
        return [self.edge("raw", "png"), self.edge("raw", "jpg"), self.edge("raw", "tiff")]

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        import rawpy
        from PIL import Image

        try:
            with rawpy.imread(str(src)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        except Exception as exc:
            raise ConversionError(f"cannot decode the RAW photo: {exc}") from exc
        image = Image.fromarray(rgb)
        params = SAVE_PARAMS.get(edge.dst, {})
        image.save(dst, PILLOW_NAMES[edge.dst], **params)
        return dst
