"""Tiny translation layer: English and Spanish, picked from the system locale.

Set ``TRANSCRIPT_LANG=en`` or ``TRANSCRIPT_LANG=es`` to force a language.
"""

from __future__ import annotations

import locale
import os
import sys

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "menu.title": "to",
        "menu.instruction": "(↑/↓ move · type to filter · Enter convert · Ctrl+C cancel)",
        "menu.via": "via {path}",
        "cancelled": "Cancelled.",
        "file.not_found": "File not found: {path}",
        "file.unknown_format": "Could not detect the format of '{path}'. Use --from to specify it.",
        "file.unknown_from": "Unknown format: '{name}'. Run 'transcript --formats' to see the supported formats.",
        "file.no_routes": "No conversions available for {fmt} with the tools installed. Run 'transcript --doctor' to see what is missing.",
        "batch.no_common": "These files have no target format in common.",
        "target.unknown": "Unknown target format: '{name}'.",
        "target.unavailable": "Cannot convert {src} to {dst}. Possible targets: {targets}",
        "target.noninteractive": "This is not an interactive terminal: pick the target with --to. Possible targets: {targets}",
        "convert.step": "{src} → {dst} with {engine}",
        "convert.done": "Saved: {path}",
        "convert.failed": "Conversion failed: {error}",
        "convert.summary_fail": "{count} file(s) could not be converted.",
        "workspace.created": "Temporary folder: {path}",
        "workspace.removed": "Temporary folder removed: {path}",
        "list.header": "{name} ({fmt}) can be converted to:",
        "doctor.header": "Conversion engines",
        "doctor.engine": "Engine",
        "doctor.status": "Status",
        "doctor.details": "Details",
        "doctor.ok": "available",
        "doctor.missing": "not found",
        "doctor.formats": "{count} formats readable, {targets} writable right now.",
        "formats.header": "Supported formats",
        "formats.format": "Format",
        "formats.ext": "Extensions",
        "formats.read": "Read",
        "formats.write": "Write",
        "cat.document": "Documents",
        "cat.spreadsheet": "Spreadsheets",
        "cat.presentation": "Presentations",
        "cat.ebook": "Ebooks",
        "cat.image": "Images",
        "cat.audio": "Audio",
        "cat.video": "Video",
        "cat.subtitle": "Subtitles",
        "cat.text": "Text",
        "cat.data": "Data",
        "cat.archive": "Archives",
        "cat.font": "Fonts",
        "fmt.txt": "Plain text",
        "fmt.code": "Source code",
        "fmt.folder": "Folder (extract)",
        "help.description": "Convert a file to another format. Run it with a file and pick the target format in the 'to' menu.",
        "help.files": "file(s) or folder to convert",
        "help.to": "target format (pdf, docx, mp3...); skips the menu",
        "help.from": "force the source format instead of detecting it",
        "help.output": "folder where the result is saved (default: next to the original)",
        "help.overwrite": "overwrite existing files instead of adding ' (1)', ' (2)'...",
        "help.list": "only list the formats the file can be converted to",
        "help.formats": "list every supported format",
        "help.doctor": "show which conversion engines are installed",
        "help.dpi": "resolution for PDF to image conversions (default: 150)",
        "help.lang": "language of the content for OCR and speech transcription (e.g. es, en)",
        "help.model": "speech recognition model: tiny, base, small, medium, large-v3 (default: small)",
        "help.verbose": "show the commands being run and the temporary folder",
        "speech.loading": "Loading speech model '{model}' (the first time it is downloaded)…",
    },
    "es": {
        "menu.title": "to",
        "menu.instruction": "(↑/↓ moverse · escribe para filtrar · Enter convertir · Ctrl+C cancelar)",
        "menu.via": "vía {path}",
        "cancelled": "Cancelado.",
        "file.not_found": "No se encuentra el fichero: {path}",
        "file.unknown_format": "No se pudo detectar el formato de '{path}'. Usa --from para indicarlo.",
        "file.unknown_from": "Formato desconocido: '{name}'. Ejecuta 'transcript --formats' para ver los formatos soportados.",
        "file.no_routes": "No hay conversiones disponibles para {fmt} con las herramientas instaladas. Ejecuta 'transcript --doctor' para ver qué falta.",
        "batch.no_common": "Estos ficheros no tienen ningún formato de destino en común.",
        "target.unknown": "Formato de destino desconocido: '{name}'.",
        "target.unavailable": "No se puede convertir {src} a {dst}. Destinos posibles: {targets}",
        "target.noninteractive": "No es un terminal interactivo: elige el destino con --to. Destinos posibles: {targets}",
        "convert.step": "{src} → {dst} con {engine}",
        "convert.done": "Guardado: {path}",
        "convert.failed": "Error en la conversión: {error}",
        "convert.summary_fail": "{count} fichero(s) no se pudieron convertir.",
        "workspace.created": "Carpeta temporal: {path}",
        "workspace.removed": "Carpeta temporal borrada: {path}",
        "list.header": "{name} ({fmt}) se puede convertir a:",
        "doctor.header": "Motores de conversión",
        "doctor.engine": "Motor",
        "doctor.status": "Estado",
        "doctor.details": "Detalles",
        "doctor.ok": "disponible",
        "doctor.missing": "no encontrado",
        "doctor.formats": "{count} formatos legibles y {targets} de destino disponibles ahora mismo.",
        "formats.header": "Formatos soportados",
        "formats.format": "Formato",
        "formats.ext": "Extensiones",
        "formats.read": "Leer",
        "formats.write": "Escribir",
        "cat.document": "Documentos",
        "cat.spreadsheet": "Hojas de cálculo",
        "cat.presentation": "Presentaciones",
        "cat.ebook": "Libros electrónicos",
        "cat.image": "Imágenes",
        "cat.audio": "Audio",
        "cat.video": "Vídeo",
        "cat.subtitle": "Subtítulos",
        "cat.text": "Texto",
        "cat.data": "Datos",
        "cat.archive": "Archivos comprimidos",
        "cat.font": "Fuentes tipográficas",
        "fmt.txt": "Texto plano",
        "fmt.code": "Código fuente",
        "fmt.folder": "Carpeta (extraer)",
        "help.description": "Convierte un fichero a otro formato. Ejecútalo con un fichero y elige el formato de destino en el menú 'to'.",
        "help.files": "fichero(s) o carpeta a convertir",
        "help.to": "formato de destino (pdf, docx, mp3...); se salta el menú",
        "help.from": "fuerza el formato de origen en lugar de detectarlo",
        "help.output": "carpeta donde se guarda el resultado (por defecto: junto al original)",
        "help.overwrite": "sobrescribe ficheros existentes en lugar de añadir ' (1)', ' (2)'...",
        "help.list": "solo lista los formatos a los que se puede convertir el fichero",
        "help.formats": "lista todos los formatos soportados",
        "help.doctor": "muestra qué motores de conversión están instalados",
        "help.dpi": "resolución para convertir PDF a imagen (por defecto: 150)",
        "help.lang": "idioma del contenido para OCR y transcripción de voz (p. ej. es, en)",
        "help.model": "modelo de reconocimiento de voz: tiny, base, small, medium, large-v3 (por defecto: small)",
        "help.verbose": "muestra los comandos ejecutados y la carpeta temporal",
        "speech.loading": "Cargando el modelo de voz '{model}' (la primera vez se descarga)…",
    },
}


def _system_language() -> str:
    for var in ("TRANSCRIPT_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var)
        if value:
            return value
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return locale.windows_locale.get(lang_id, "")
        except Exception:
            return ""
    try:
        return locale.getlocale()[0] or ""
    except ValueError:
        return ""


def current_language() -> str:
    code = _system_language().lower()[:2]
    return code if code in MESSAGES else "en"


LANG = current_language()


LETTER_REGIONS = {"US", "CA", "MX", "PH", "CL", "CO", "VE", "PR", "CR", "GT", "PA", "SV", "DO"}


def paper_size() -> str:
    """'us-letter' in the Americas regions that use it, 'a4' everywhere else."""
    region = _system_language().split(".")[0].replace("-", "_").split("_")[1:2]
    return "us-letter" if region and region[0].upper() in LETTER_REGIONS else "a4"


def t(key: str, default: str | None = None, **kwargs: object) -> str:
    text = MESSAGES[LANG].get(key) or MESSAGES["en"].get(key) or default or key
    return text.format(**kwargs) if kwargs else text
