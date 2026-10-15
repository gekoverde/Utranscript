"""Structured data: JSON, YAML, TOML, XML, CSV, Excel, property lists, INI..."""

from __future__ import annotations

import configparser
import csv
import datetime
import html
import importlib.util
import io
import json
import plistlib
import re
import sys
from pathlib import Path
from typing import Any

from .base import ConversionError, Converter, Edge
from .text import read_text

DATA_FORMATS = ("json", "jsonl", "yaml", "toml", "xml", "plist", "ini", "csv", "tsv", "xlsx")
SPREADSHEETS = ("xlsx", "xls")
TABULAR = ("csv", "tsv")


class Tables(dict):
    """Several named tables (the sheets of a workbook)."""


# reading ---------------------------------------------------------------------------------


def load(path: Path, fmt: str) -> Any:
    if fmt == "json":
        return json.loads(read_text(path))
    if fmt == "jsonl":
        return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]
    if fmt == "yaml":
        import yaml

        docs = list(yaml.safe_load_all(read_text(path)))
        return docs[0] if len(docs) == 1 else docs
    if fmt == "toml":
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib
        return tomllib.loads(read_text(path))
    if fmt == "xml":
        import xmltodict

        return xmltodict.parse(path.read_bytes())
    if fmt == "plist":
        with open(path, "rb") as fh:
            return plistlib.load(fh)
    if fmt == "ini":
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read_string(read_text(path))
        data: dict[str, Any] = {}
        if parser.defaults():
            data["DEFAULT"] = dict(parser.defaults())
        for section in parser.sections():
            data[section] = {k: v for k, v in parser.items(section, raw=True) if k not in parser.defaults()}
        return data
    if fmt in TABULAR:
        return _read_csv(path, "\t" if fmt == "tsv" else None)
    if fmt == "xlsx":
        return _read_xlsx(path)
    if fmt == "xls":
        return _read_xls(path)
    raise ConversionError(f"cannot read {fmt}")


_INT = re.compile(r"-?(0|[1-9]\d{0,17})")
_FLOAT = re.compile(r"-?(0|[1-9]\d*)\.\d+")


def _typed_columns(header: list[str], rows: list[list[str]]) -> list[dict[str, Any]]:
    """Turn numeric columns into numbers. A column is numeric only if every value is,
    so codes such as '01234' or '+34 600...' keep their exact text."""
    converters = []
    for index in range(len(header)):
        values = [row[index].strip() for row in rows if index < len(row) and row[index].strip()]
        if values and all(_INT.fullmatch(v) for v in values):
            converters.append(int)
        elif values and all(_INT.fullmatch(v) or _FLOAT.fullmatch(v) for v in values):
            converters.append(float)
        else:
            converters.append(None)
    records = []
    for row in rows:
        record = {}
        for index, name in enumerate(header):
            value = row[index] if index < len(row) else ""
            convert = converters[index]
            record[name] = convert(value) if convert and value.strip() else value
        records.append(record)
    return records


def _read_csv(path: Path, delimiter: str | None) -> list[dict[str, Any]]:
    text = read_text(path)
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return []
    header = _unique_header(rows[0])
    return _typed_columns(header, [row for row in rows[1:] if any(cell.strip() for cell in row)])


def _unique_header(cells: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    header = []
    for index, cell in enumerate(cells, 1):
        name = str(cell).strip() if cell not in (None, "") else f"column{index}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        header.append(name)
    return header


def _read_xlsx(path: Path) -> Any:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return _tables((sheet.title, sheet.iter_rows(values_only=True)) for sheet in workbook.worksheets)
    finally:
        workbook.close()


def _read_xls(path: Path) -> Any:
    import xlrd

    workbook = xlrd.open_workbook(str(path))

    def value(cell):
        if cell.ctype == xlrd.XL_CELL_DATE:
            return xlrd.xldate_as_datetime(cell.value, workbook.datemode)
        if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
            return int(cell.value)
        if cell.ctype == xlrd.XL_CELL_BOOLEAN:
            return bool(cell.value)
        if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
            return None
        return cell.value

    sheets = workbook.sheets()
    return _tables((sheet.name, ([value(c) for c in sheet.row(i)] for i in range(sheet.nrows))) for sheet in sheets)


def _tables(sheets) -> Any:
    """Records of every non empty sheet: a list for one sheet, Tables for several."""
    tables = Tables()
    for title, sheet_rows in sheets:
        rows = [list(r) for r in sheet_rows]
        while rows and all(v is None for v in rows[-1]):
            rows.pop()
        if not rows:
            continue
        header = _unique_header(rows[0])
        tables[title] = [
            {h: _plain(v) for h, v in zip(header, row, strict=False)} for row in rows[1:] if not all(v is None for v in row)
        ]
    if len(tables) == 1:
        return next(iter(tables.values()))
    return tables


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    return value


# writing ---------------------------------------------------------------------------------


def dump(data: Any, path: Path, fmt: str) -> Path:
    if fmt == "json":
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_default) + "\n", encoding="utf-8")
    elif fmt == "jsonl":
        items = data if isinstance(data, list) else [data]
        lines = (json.dumps(item, ensure_ascii=False, default=_default) for item in items)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif fmt == "yaml":
        import yaml

        text = yaml.safe_dump(_jsonable(data), allow_unicode=True, sort_keys=False, default_flow_style=False)
        path.write_text(text, encoding="utf-8")
    elif fmt == "toml":
        import tomli_w

        root = _drop_none(_jsonable(data))
        if not isinstance(root, dict):
            root = {"items": root}
        path.write_text(tomli_w.dumps(root), encoding="utf-8")
    elif fmt == "xml":
        import xmltodict

        path.write_text(xmltodict.unparse(_xml_root(data), pretty=True, indent="  "), encoding="utf-8")
    elif fmt == "plist":
        root = _drop_none(_jsonable(data))
        with open(path, "wb") as fh:
            plistlib.dump(root, fh, sort_keys=False)
    elif fmt == "ini":
        _write_ini(data, path)
    elif fmt in TABULAR:
        return _write_tables(data, path, "\t" if fmt == "tsv" else ",")
    elif fmt == "xlsx":
        _write_xlsx(data, path)
    elif fmt == "html":
        _write_html(data, path)
    else:
        raise ConversionError(f"cannot write {fmt}")
    return path


def _default(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _jsonable(data: Any) -> Any:
    """Normalise to plain JSON-like types (YAML/TOML/plist writers are picky)."""
    return json.loads(json.dumps(data, default=_default))


def _drop_none(data: Any) -> Any:
    if isinstance(data, dict):
        return {str(k): _drop_none(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [_drop_none(v) for v in data if v is not None]
    return data


_XML_NAME = re.compile(r"[^\w.\-]")


def _xml_key(key: Any) -> str:
    name = _XML_NAME.sub("_", str(key)) or "item"
    if not (name[0].isalpha() or name[0] == "_") or name.lower().startswith("xml"):
        name = "_" + name
    return name


def _xml_clean(data: Any) -> Any:
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            key = str(key)
            name = key if key.startswith(("@", "#")) else _xml_key(key)
            out[name] = _xml_clean(value)
        return out
    if isinstance(data, list):
        return [_xml_clean(v) for v in data]
    if isinstance(data, bool):
        return "true" if data else "false"
    return data


def _xml_root(data: Any) -> dict:
    data = _xml_clean(_jsonable(data))
    if isinstance(data, dict) and len(data) == 1 and not isinstance(next(iter(data.values())), list):
        return data
    if isinstance(data, list):
        return {"root": {"item": data}}
    return {"root": data}


def _write_ini(data: Any, path: Path) -> None:
    if not isinstance(data, dict):
        raise ConversionError("only key/value data (an object with sections) can be written as INI")
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    loose = {}
    for key, value in data.items():
        if isinstance(value, dict):
            section = "DEFAULT" if key == "DEFAULT" else str(key)
            if section != "DEFAULT":
                parser.add_section(section)
            for k, v in value.items():
                parser.set(section, str(k), _ini_value(v))
        else:
            loose[str(key)] = _ini_value(value)
    if loose:
        if not parser.has_section("main"):
            parser.add_section("main")
        for k, v in loose.items():
            parser.set("main", k, v)
    with open(path, "w", encoding="utf-8") as fh:
        parser.write(fh)


def _ini_value(value: Any) -> str:
    if value is None:
        return ""
    return str(_cell(value))


def as_rows(data: Any) -> tuple[list[str], list[list[Any]]]:
    """Turn data into a table (header, rows) or explain why it is not tabular."""
    # Unwrap single-key wrappers such as {"items": [...]} or {"root": {"row": [...]}}.
    while isinstance(data, dict) and len(data) == 1 and isinstance(next(iter(data.values())), (dict, list)):
        data = next(iter(data.values()))
    if isinstance(data, dict):
        records = [v for v in data.values() if isinstance(v, list) and v and all(isinstance(i, dict) for i in v)]
        if len(records) == 1:  # e.g. {"@version": "1", "row": [{...}, {...}]}
            data = records[0]
        else:
            return ["key", "value"], [[k, _cell(v)] for k, v in data.items()]
    if not isinstance(data, list):
        return ["value"], [[_cell(data)]]
    if all(isinstance(item, dict) for item in data):
        header: list[str] = []
        for item in data:
            for key in item:
                if str(key) not in header:
                    header.append(str(key))
        return header, [[_cell(item.get(h, item.get(_maybe_int(h)))) for h in header] for item in data]
    if all(isinstance(item, list) for item in data) and data:
        width = max(len(row) for row in data)
        header = [str(v) for v in data[0]] + [f"column{i}" for i in range(len(data[0]) + 1, width + 1)]
        return header, [[_cell(v) for v in row] for row in data[1:]]
    return ["value"], [[_cell(item)] for item in data]


def _maybe_int(key: str) -> Any:
    return int(key) if key.isdigit() else key


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=_default)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _write_tables(data: Any, path: Path, delimiter: str) -> Path:
    if isinstance(data, Tables):
        folder = path.with_suffix("")
        folder.mkdir()
        for name, table in data.items():
            safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "sheet"
            _write_table(table, folder / (safe + path.suffix), delimiter)
        return folder
    _write_table(data, path, delimiter)
    return path


def _write_table(data: Any, path: Path, delimiter: str) -> None:
    header, rows = as_rows(data)
    # UTF-8 with BOM so that Excel shows accents correctly when opening the file.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter)
        writer.writerow(header)
        writer.writerows(["" if v is None else v for v in row] for row in rows)


def _write_xlsx(data: Any, path: Path) -> None:
    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    tables = data.items() if isinstance(data, Tables) else [("Sheet1", data)]
    used: set[str] = set()
    for name, table in tables:
        title = re.sub(r"[\[\]:*?/\\]", "_", str(name))[:31] or "Sheet"
        while title in used:
            title = title[:28] + f"_{len(used)}"
        used.add(title)
        sheet = workbook.create_sheet(title)
        header, rows = as_rows(table)
        sheet.append(header)
        for row in rows:
            sheet.append([_xlsx_cell(v) for v in row])
    workbook.save(path)


def _write_html(data: Any, path: Path) -> None:
    tables = data.items() if isinstance(data, Tables) else [(None, data)]
    parts = []
    for name, table in tables:
        header, rows = as_rows(table)
        if name is not None:
            parts.append(f"<h2>{html.escape(str(name))}</h2>")
        head = "".join(f"<th>{html.escape(str(h))}</th>" for h in header)
        body = "\n".join(
            "<tr>" + "".join(f"<td>{html.escape('' if v is None else str(v))}</td>" for v in row) + "</tr>" for row in rows
        )
        parts.append(f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>\n{body}\n</tbody>\n</table>")
    path.write_text(
        '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(path.stem)}</title>\n"
        "<style>table{border-collapse:collapse}th,td{border:1px solid #999;padding:4px 8px}</style>\n"
        "</head>\n<body>\n" + "\n".join(parts) + "\n</body>\n</html>\n",
        encoding="utf-8",
    )


def _xlsx_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, datetime.datetime, datetime.date)):
        return value
    return str(value)


class DataConverter(Converter):
    name = "Transcript data"

    def edges(self):
        sources = list(DATA_FORMATS)
        if importlib.util.find_spec("xlrd"):
            sources.append("xls")
        edges = []
        for src in sources:
            for dst in DATA_FORMATS:
                if src != dst:
                    # A workbook with several sheets becomes a folder of CSV files.
                    terminal = src in SPREADSHEETS and dst in TABULAR
                    edges.append(self.edge(src, dst, terminal=terminal))
        # Every sheet as an HTML table, the way into documents and PDF.
        edges += [self.edge(src, "html") for src in sources if src in SPREADSHEETS]
        return edges

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        try:
            data = load(src, edge.src)
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"cannot read the {edge.src.upper()} file: {exc}") from exc
        try:
            return dump(data, dst, edge.dst)
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"cannot write {edge.dst.upper()}: {exc}") from exc
