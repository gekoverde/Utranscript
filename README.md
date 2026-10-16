# Utranscript

Herramienta de terminal para pasar **cualquier fichero de un formato a otro**, en Windows,
Linux y macOS. Igual que escribes `claude` y se abre Claude Code, aquí escribes:

```
transcript informe.docx
```

y aparece un menú con la cabecera **`to`** para elegir el formato de destino:

```
informe.docx  ·  Word  ·  48.2 KB
 to (↑/↓ moverse · escribe para filtrar · Enter convertir · Ctrl+C cancelar)
   ── Documentos ──
 ❯ PDF                        .pdf
   Word 97-2003               .doc
   OpenDocument Text          .odt
   Rich Text Format           .rtf
   Markdown                   .md
   HTML                       .html
   ...
   ── Libros electrónicos ──
   EPUB                       .epub
   ── Imágenes ──
   PNG                        .png     vía PDF
```

Al pulsar Enter, Transcript crea una **carpeta temporal**, hace allí la conversión (con todos los
pasos intermedios que hagan falta), deja el resultado junto al fichero original y **borra la
carpeta temporal**. La carpeta se borra siempre: al terminar bien, si hay un error y también si
cancelas con Ctrl+C.

```
  DOCX → PDF con LibreOffice ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:02
✔ Guardado: C:\Users\ana\Documentos\informe.pdf
```

Si ya existe un fichero con ese nombre no se sobrescribe: se guarda como `informe (1).pdf`.

## Instalación

Necesitas **Python 3.10 o superior** ([python.org](https://www.python.org/downloads/); en
Windows marca *"Add python.exe to PATH"* al instalarlo).

La forma recomendada es [pipx](https://pipx.pypa.io), que instala el comando `transcript` de
forma global y aislada:

**Windows (PowerShell)**

```powershell
py -m pip install --user pipx
py -m pipx ensurepath          # cierra y vuelve a abrir la terminal después
pipx install git+https://github.com/gekoverde/Utranscript.git
```

**Linux / macOS**

```bash
python3 -m pip install --user pipx    # o: sudo apt install pipx
python3 -m pipx ensurepath
pipx install git+https://github.com/gekoverde/Utranscript.git
```

También puedes clonar el repositorio y ejecutar `install.ps1` (Windows) o `./install.sh`
(Linux/macOS), que hacen lo mismo. Con [uv](https://docs.astral.sh/uv/) basta
`uv tool install git+https://github.com/gekoverde/Utranscript.git`.

Para actualizar: `pipx upgrade transcript-cli`. Para desinstalar: `pipx uninstall transcript-cli`.

> **Windows en ARM** (Surface Pro X, Snapdragon...): pandoc y Typst no publican paquetes para esa
> arquitectura, así que no se instalan solos. Instala pandoc aparte (`winget install JohnMacFarlane.Pandoc`);
> los PDF de documentos saldrán entonces a través de LibreOffice.

### Qué viene incluido y qué es opcional

Con la instalación normal ya funcionan documentos (pandoc va incluido), PDF (Typst y PDFium
incluidos, **no hace falta LaTeX**), imágenes, audio y vídeo (FFmpeg va incluido), datos,
subtítulos, fuentes y archivos comprimidos. Estos extras amplían lo que se puede hacer:

| Extra | Qué añade | Cómo instalarlo |
|---|---|---|
| **LibreOffice** | Word, Excel, PowerPoint, Visio, Publisher, Pages, Keynote... con máxima fidelidad (`.doc`, `.xls`, `.ppt`, `.odp`...) | Windows: `winget install TheDocumentFoundation.LibreOffice` · Linux: `sudo apt install libreoffice` |
| **Transcripción de voz** | Audio/vídeo → texto, SRT o VTT (y de ahí a Word, PDF...) | `pipx inject transcript-cli faster-whisper` |
| **Tesseract OCR** | Imagen o PDF escaneado → texto | Windows: `winget install UB-Mannheim.TesseractOCR` · Linux: `sudo apt install tesseract-ocr tesseract-ocr-spa` |
| **Calibre** | Libros Kindle (MOBI, AZW3) | Windows: `winget install calibre.calibre` · Linux: `sudo apt install calibre` |
| **7-Zip** | Extraer RAR, ISO y CAB | Windows: `winget install 7zip.7zip` · Linux: `sudo apt install 7zip` |
| **SVG** | Renderizar SVG | `pipx inject transcript-cli cairosvg` (necesita la librería cairo), o instala `librsvg`/Inkscape |
| **RAW de cámara** | DNG, CR2, NEF, ARW... | `pipx inject transcript-cli rawpy` |

`transcript --doctor` muestra qué motores tienes y cómo instalar los que faltan. Transcript
detecta los programas en el `PATH` y en sus rutas habituales de Windows (`C:\Program Files\...`).

## Uso

```
transcript FICHERO [FICHERO ...] [opciones]
```

| Opción | Descripción |
|---|---|
| *(sin opciones)* | Abre el menú `to` para elegir el formato de destino |
| `-t, --to FORMATO` | Convierte directamente sin menú: `--to pdf`, `--to mp3`, `--to .jpg` |
| `-o, --output CARPETA` | Dónde guardar el resultado (por defecto, junto al original) |
| `-l, --list` | Lista a qué formatos se puede convertir el fichero |
| `-f, --from FORMATO` | Fuerza el formato de origen (si la extensión no lo dice) |
| `--overwrite` | Sobrescribe ficheros existentes (y la carpeta `nombre_media` que los acompaña) en vez de crear `nombre (1).ext`. Nunca borra otras carpetas ni el fichero original |
| `--dpi N` | Resolución al convertir PDF a imágenes (por defecto 150) |
| `--lang CÓDIGO` | Idioma del contenido para OCR y transcripción de voz (`es`, `en`...) |
| `--model NOMBRE` | Modelo de voz: `tiny`, `base`, `small` (por defecto), `medium`, `large-v3` |
| `--formats` | Lista todos los formatos soportados |
| `--doctor` | Muestra los motores de conversión instalados |
| `-v, --verbose` | Muestra los comandos ejecutados y la carpeta temporal |

Ejemplos:

```bash
transcript foto.heic                      # menú: JPG, PNG, WebP, PDF...
transcript informe.docx --to pdf
transcript entrevista.mp4 --to mp3        # extrae el audio
transcript entrevista.mp4 --to srt        # subtítulos con reconocimiento de voz
transcript entrevista.mp4 --to docx       # transcripción en Word (vía TXT)
transcript datos.csv --to xlsx
transcript libro.xlsx --to json           # cada hoja como una lista de filas
transcript presentacion.pptx --to pdf
transcript escaneo.pdf --to txt           # con Tesseract, usa OCR si el PDF no tiene texto
transcript documento.pdf --to png         # una imagen por página (en una carpeta)
transcript copia.rar --to zip
transcript mi_carpeta --to 7z             # también funciona con carpetas
transcript *.png --to webp                # varios ficheros a la vez
```

Si arrastras un fichero a la terminal se pega su ruta, así que basta con escribir `transcript `
y soltar el fichero encima.

## Formatos

Más de 120 formatos (`transcript --formats` muestra la lista exacta con lo que tengas instalado):

| Categoría | Formatos |
|---|---|
| Documentos | PDF, Word (DOCX/DOC), ODT, RTF, Markdown, HTML, LaTeX, Typst, reStructuredText, AsciiDoc, Org, Textile, MediaWiki, DocBook, Jupyter Notebook, OPML, WordPerfect, Works, Pages, Visio, Publisher, ODG |
| Hojas de cálculo | Excel (XLSX/XLS), ODS, CSV, TSV, Numbers |
| Presentaciones | PowerPoint (PPTX/PPT), ODP, Keynote |
| Libros electrónicos | EPUB, MOBI, AZW3, FB2, CBZ (cómic) |
| Imágenes | PNG, JPEG, WebP, AVIF, HEIC, GIF (animados incluidos), BMP, TIFF, ICO, ICNS, SVG, PSD, TGA, JPEG 2000, Netpbm, PCX, DDS, QOI, EMF/WMF, RAW de cámara |
| Audio | MP3, WAV, FLAC, M4A, AAC, OGG, Opus, WMA, AIFF, AC3, MKA, AMR, APE, WavPack, CAF, AU, MP2, DTS |
| Vídeo | MP4, MKV, WebM, MOV, AVI, WMV, FLV, MPEG, M4V, OGV, 3GP, TS/MTS/M2TS, VOB, MXF, RealMedia (y a GIF animado) |
| Subtítulos | SRT, WebVTT, ASS, SSA, MicroDVD, TTML, SAMI |
| Texto | Texto plano (cualquier codificación), código fuente con resaltado de sintaxis (Python, JS, C, Java, Go, Rust...) |
| Datos | JSON, JSON Lines, YAML, TOML, XML, plist, INI |
| Comprimidos | ZIP, 7z, TAR, TAR.GZ, TAR.BZ2, TAR.XZ, RAR, ISO, CAB, carpetas |
| Fuentes | TTF, OTF, WOFF, WOFF2 |

### Cómo elige la conversión

Cada motor sabe hacer algunas conversiones directas (pandoc: Markdown → Word; LibreOffice:
Word → PDF; FFmpeg: MP4 → MP3...). Transcript une todas en un grafo y busca la **ruta más
barata**, encadenando pasos cuando no hay conversión directa. Por ejemplo, sin LibreOffice
un Word se convierte a PDF así: `DOCX → Typst (pandoc) → PDF (Typst)`. En el menú, esas rutas
indirectas aparecen marcadas con `vía ...`.

Para que no salgan opciones absurdas, una ruta puede cambiar de tipo de fichero como mucho
dos veces (vídeo → texto → Word sí; vídeo → texto → PDF → PNG no).

Cuando es posible se convierte sin pérdida: de MKV a MP4 con H.264, por ejemplo, se copian las
pistas en vez de recomprimir, así que tarda segundos.

### Seguridad

- El resultado se escribe primero con un nombre oculto y solo se renombra al final, así que un
  fallo (disco lleno, Ctrl+C) nunca deja un fichero a medias ni borra el anterior.
- Si cancelas o cierras la terminal, se detienen también los programas externos (LibreOffice,
  FFmpeg...) antes de borrar la carpeta temporal.
- Un documento descargado no puede colar ficheros privados tuyos en el resultado: se ignoran las
  imágenes con rutas absolutas o fuera de su carpeta, y se rechazan los `include` que apunten
  fuera de ella. Los comprimidos con rutas o enlaces que salen de su carpeta también se rechazan.

## Idioma

Los mensajes salen en español o en inglés según el idioma del sistema. Para forzarlo:
`TRANSCRIPT_LANG=es` o `TRANSCRIPT_LANG=en`.

El tamaño de página de los PDF (A4 o Carta) sigue la región del sistema, no el idioma de los mensajes.

Variables de entorno opcionales:

| Variable | Para qué |
|---|---|
| `TRANSCRIPT_TMPDIR` | Dónde crear la carpeta temporal |
| `TRANSCRIPT_ENCODING` | Codificación de los ficheros de texto antiguos si se detecta mal (p. ej. `cp1250`). En Windows se prueba antes la del sistema |
| `TRANSCRIPT_WHISPER_MODEL` | Modelo de voz por defecto (`small`) |
| `TRANSCRIPT_WHISPER_DEVICE` | `cuda` para transcribir con una GPU NVIDIA (necesita cuBLAS 12 y cuDNN 9; si falla, se usa la CPU) |
| `TRANSCRIPT_FFMPEG`, `TRANSCRIPT_PANDOC`, `TRANSCRIPT_SOFFICE`, `TRANSCRIPT_TESSERACT`, `TRANSCRIPT_EBOOK_CONVERT`, `TRANSCRIPT_7Z` | Rutas a los programas, si no están en el `PATH` |

## Desarrollo

```bash
git clone https://github.com/gekoverde/Utranscript.git
cd Transcript
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Estructura:

- `transcript/cli.py` — comando `transcript` y opciones.
- `transcript/ui.py` — el menú `to` y las barras de progreso.
- `transcript/formats.py` — catálogo de formatos y detección (por extensión y por contenido).
- `transcript/planner.py` — búsqueda de la mejor ruta de conversión.
- `transcript/engine.py` — carpeta temporal y ejecución de los pasos.
- `transcript/converters/` — un módulo por motor (pandoc, LibreOffice, FFmpeg, Pillow...).

Añadir un formato nuevo consiste en darlo de alta en `formats.py` y declarar sus conversiones
(`edges`) en el conversor que lo sepa manejar.

## Licencia

[MIT](LICENSE). Todas las dependencias son de código abierto y compatibles; el detalle de cada
una está en [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
