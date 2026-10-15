"""Office documents with LibreOffice (when installed): Word, Excel, PowerPoint, Visio..."""

from __future__ import annotations

import csv
from pathlib import Path

from .. import tools
from .base import ConversionError, Converter, Edge, move_into
from .text import read_text

WRITER_IN = ("doc", "docx", "odt", "rtf", "txt", "html", "wpd", "wps", "pages")
CALC_IN = ("xls", "xlsx", "ods", "csv", "tsv", "numbers")
IMPRESS_IN = ("ppt", "pptx", "odp", "key")
DRAW_IN = ("odg", "vsdx", "pub", "emf", "svg")

WRITER_OUT = {
    "pdf": "pdf:writer_pdf_Export",
    "docx": "docx:MS Word 2007 XML",
    "doc": "doc:MS Word 97",
    "odt": "odt:writer8",
    "rtf": "rtf:Rich Text Format",
    "txt": "txt:Text (encoded):UTF8",
    "html": "html:XHTML Writer File:UTF8",
    "epub": "epub:EPUB",
}
CALC_OUT = {
    "pdf": "pdf:calc_pdf_Export",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
    "xls": "xls:MS Excel 97",
    "ods": "ods:calc8",
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
    "html": "html:HTML (StarCalc)",
}
IMPRESS_OUT = {
    "pdf": "pdf:impress_pdf_Export",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "ppt": "ppt:MS PowerPoint 97",
    "odp": "odp:impress8",
}
DRAW_OUT = {
    "pdf": "pdf:draw_pdf_Export",
    "png": "png:draw_png_Export",
    "svg": "svg:draw_svg_Export",
    "odg": "odg:draw8",
}
FAMILIES = (
    (WRITER_IN, WRITER_OUT),
    (CALC_IN, CALC_OUT),
    (IMPRESS_IN, IMPRESS_OUT),
    (DRAW_IN, DRAW_OUT),
)


def _export_filter(src: str, dst: str) -> str:
    if src == "pdf":
        return WRITER_OUT[dst]
    for inputs, outputs in FAMILIES:
        if src in inputs and dst in outputs:
            return outputs[dst]
    raise ConversionError(f"LibreOffice cannot convert {src} to {dst}")


def _csv_import_filter(path: Path, tsv: bool) -> str:
    delimiter = "\t"
    if not tsv:
        sample = read_text(path)[:20000]
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    # separator, text delimiter ("), charset (76 = UTF-8), first line
    return f"Text - txt - csv (StarCalc):{ord(delimiter)},34,76,1"


class LibreOfficeConverter(Converter):
    name = "LibreOffice"
    hint = (
        "https://www.libreoffice.org/download  ·  Windows: winget install TheDocumentFoundation.LibreOffice"
        "  ·  Linux: sudo apt install libreoffice"
    )

    def available(self) -> bool:
        return tools.soffice() is not None

    def details(self) -> str:
        return tools.soffice() or ""

    def edges(self):
        def cost(src: str, dst: str) -> float:
            if src in ("csv", "tsv", "html"):
                return 1.5  # the built-in CSV reader and pandoc's HTML reader do better
            if src == "svg":
                return 2.0
            if src == "txt":
                return 1.2
            if dst in ("txt", "html", "csv"):
                return 1.5
            if dst == "epub":
                return 2.0
            return 1.0

        edges = []
        for inputs, outputs in FAMILIES:
            edges += self.matrix(inputs, outputs, cost)
        # PDF import into Writer keeps the text editable (layout is approximated).
        edges += [self.edge("pdf", "docx", cost=2.0), self.edge("pdf", "odt", cost=2.0)]
        return edges

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        export = _export_filter(edge.src, edge.dst)
        work = ctx.scratch("libreoffice")
        infilter = None
        if edge.src == "pdf":
            infilter = "writer_pdf_import"
        elif edge.src in ("csv", "tsv"):
            infilter = _csv_import_filter(src, edge.src == "tsv")
        elif edge.src == "html":
            infilter = "HTML (StarWriter)"  # open in Writer, not Writer/Web, so every export works
        elif edge.src == "txt":
            utf8 = work / src.name
            utf8.write_text(read_text(src), encoding="utf-8")
            src = utf8
            infilter = "Text (encoded):UTF8"

        profile = ctx.workspace / "_libreoffice_profile"
        outdir = work / "out"
        cmd = [
            tools.soffice(),
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--headless",
            "--invisible",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
        ]
        if infilter:
            cmd.append(f"--infilter={infilter}")
        cmd += ["--convert-to", export, "--outdir", str(outdir), str(src)]
        proc = ctx.run(cmd, timeout=900)
        produced = outdir / (src.stem + "." + export.split(":", 1)[0])
        if not produced.exists():
            message = tools.tail((proc.stdout or "") + "\n" + (proc.stderr or ""), 3)
            raise ConversionError(f"LibreOffice could not convert the file: {message}")
        return move_into(produced, dst)
