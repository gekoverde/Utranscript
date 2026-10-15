# Licencias de terceros / Third-party licenses

Transcript se publica bajo la licencia **MIT** (ver [`LICENSE`](LICENSE)). No copia código de
otros proyectos: los usa como dependencias que se instalan desde PyPI o como programas
externos que se ejecutan por separado. Todas son de código abierto y compatibles con un
proyecto MIT de código abierto.

Transcript is MIT licensed. It does not vendor third-party code: it depends on the packages
below (installed from PyPI) and runs some external programs as separate processes.

## Dependencias de Python (se instalan con Transcript)

| Paquete | Licencia | Para qué se usa |
|---|---|---|
| [rich](https://github.com/Textualize/rich) | MIT | Salida en terminal y barras de progreso |
| [questionary](https://github.com/tmbo/questionary) (+ prompt_toolkit, BSD-3) | MIT | Menú interactivo "to" |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | MIT | Detección de codificación de texto |
| [Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU (HPND) | Imágenes |
| [pillow-heif](https://github.com/bigcat88/pillow_heif) | BSD-3-Clause ¹ | Fotos HEIC/HEIF |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | Apache-2.0 / BSD-3-Clause | Texto e imágenes de PDF |
| [typst](https://github.com/messense/typst-py) | Apache-2.0 | Generar PDF sin LaTeX |
| [pypandoc_binary](https://github.com/JessicaTegner/pypandoc) | MIT ² | Incluye el programa pandoc |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | BSD-2-Clause ² | Incluye el programa FFmpeg |
| [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) | MIT | Excel (.xlsx) |
| [xlrd](https://github.com/python-excel/xlrd) | BSD-3-Clause | Excel antiguo (.xls) |
| [PyYAML](https://github.com/yaml/pyyaml) | MIT | YAML |
| [tomli](https://github.com/hukkin/tomli) / [tomli-w](https://github.com/hukkin/tomli-w) | MIT | TOML |
| [xmltodict](https://github.com/martinblech/xmltodict) | MIT | XML |
| [pysubs2](https://github.com/tkarabela/pysubs2) | MIT | Subtítulos |
| [fontTools](https://github.com/fonttools/fonttools) (+ brotli, MIT) | MIT | Fuentes tipográficas |
| [py7zr](https://github.com/miurahr/py7zr) | LGPL-2.1-or-later ³ | Archivos 7z |
| [Pygments](https://github.com/pygments/pygments) | BSD-2-Clause | Resaltado de código |

## Dependencias opcionales (extras)

| Paquete | Extra | Licencia | Para qué se usa |
|---|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | `speech` | MIT | Transcribir voz a texto/subtítulos ⁴ |
| [CairoSVG](https://github.com/Kozea/CairoSVG) | `svg` | LGPL-3.0-or-later ³ | Renderizar SVG |
| [rawpy](https://github.com/letmaik/rawpy) | `raw` | MIT (incluye LibRaw, LGPL-2.1/CDDL-1.0) | Fotos RAW de cámara |

## Programas externos (opcionales, se detectan si están instalados)

Se ejecutan como procesos independientes; Transcript no los enlaza ni los redistribuye.

| Programa | Licencia | Para qué se usa |
|---|---|---|
| [LibreOffice](https://www.libreoffice.org) | MPL-2.0 | Word/Excel/PowerPoint/Visio con máxima fidelidad |
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) | Apache-2.0 | Texto de imágenes y PDF escaneados |
| [Calibre](https://calibre-ebook.com) (`ebook-convert`) | GPL-3.0 | Libros Kindle (MOBI/AZW3) |
| [7-Zip](https://www.7-zip.org) / p7zip | LGPL-2.1 (+ restricción unRAR) | Extraer RAR, ISO, CAB |
| [librsvg](https://gitlab.gnome.org/GNOME/librsvg) (`rsvg-convert`) / [Inkscape](https://inkscape.org) | LGPL-2.1 / GPL-2.0 | Alternativas para SVG |
| LaTeX (xelatex, lualatex, tectonic...) | varias (LPPL, MIT...) | Motor PDF alternativo para pandoc |

## Notas

1. Las *wheels* binarias de pillow-heif incluyen libheif y libde265 (LGPL-3.0) y x265 (GPL-2.0).
2. pypandoc_binary incluye el ejecutable de **pandoc** (GPL-2.0-or-later) e imageio-ffmpeg un
   ejecutable de **FFmpeg** (LGPL/GPL según la compilación). Transcript los ejecuta como
   programas independientes y no los modifica, por lo que su licencia no se extiende al código
   de Transcript. Si alguna vez se redistribuye un paquete que los incluya (por ejemplo un
   instalador `.exe`), hay que acompañarlo de sus licencias y de la oferta de código fuente que
   exige la GPL.
3. Las bibliotecas LGPL se importan sin modificar y el usuario puede sustituirlas libremente
   (son paquetes de Python normales), que es lo que exige la LGPL.
4. Los modelos de Whisper (licencia MIT, de OpenAI) se descargan desde Hugging Face la primera
   vez que se usan.
