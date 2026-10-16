"""Regression tests for the command line, the "to" menu, the planner and format detection."""

from __future__ import annotations

import bz2
import gzip
import io
import json
import lzma
import os
import signal
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from conftest import make_font

from transcript import cli, formats, i18n, tools
from transcript.converters.base import Converter, Edge
from transcript.planner import plan
from transcript.ui import choose_target

C = Converter()


def e(src: str, dst: str) -> Edge:
    return Edge(src, dst, C)


# the "to" menu ---------------------------------------------------------------------------------


def drive_menu(monkeypatch, routes, *answers: str):
    """Run the real menu, typing ``answers[n]`` into the n-th prompt. Returns (choice, prompts, choices)."""
    questionary = pytest.importorskip("questionary")
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    real_select = questionary.select
    keys = iter(answers)
    seen: list[list] = []

    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):

        def select(*args, **kwargs):
            seen.append(kwargs["choices"])
            pipe.send_text(next(keys))
            return real_select(*args, **kwargs)

        monkeypatch.setattr(questionary, "select", select)
        return choose_target(routes), len(seen), seen[0]


def subtitle_routes():
    return plan("srt", [e("srt", "vtt"), e("srt", "txt"), e("txt", "pdf")])


def test_menu_filter_ignores_the_route_text(monkeypatch):
    routes = subtitle_routes()
    assert routes["pdf"].via == ["txt"]
    chosen, prompts, choices = drive_menu(monkeypatch, routes, "txt\r")
    assert (chosen, prompts) == ("txt", 1)  # not "PDF  .pdf  via TXT", listed before it
    pdf = next(c for c in choices if c.value == "pdf")
    assert pdf.title.endswith("via TXT")  # shown on every row...
    assert "txt" not in pdf.title.lower()  # ...but not searched


def test_menu_asks_again_when_enter_lands_on_a_heading(monkeypatch):
    # Nothing matches "zzz", and "doc" only matches the "Documents" heading: Enter returns the heading.
    chosen, prompts, _ = drive_menu(monkeypatch, subtitle_routes(), "zzz\r", "doc\r", "\r")
    assert (chosen, prompts) == ("vtt", 3)


def test_unknown_menu_answer_is_a_cancel(tmp_path, monkeypatch, capsys):
    src = tmp_path / "data.json"
    src.write_text('{"a": 1}')
    monkeypatch.setattr(cli, "is_interactive", lambda: True)
    monkeypatch.setattr(cli, "choose_target", lambda routes: "── Data ──")
    assert cli.main([str(src)]) == 130
    assert "Cancelled" in capsys.readouterr().err


# planner: content checks beyond the first step ---------------------------------------------


def test_content_check_applies_while_the_route_stays_in_the_category():
    edges = [e("mp4", "mp3"), e("mp4", "mkv"), e("mkv", "mp3"), e("mp4", "gif"), e("gif", "png")]

    def no_sound_or_png(edge):
        return edge.dst not in ("mp3", "png")

    routes = plan("mp4", edges, no_sound_or_png, check_same_category=True)
    assert "mp3" not in routes and "mkv" in routes
    assert routes["png"].via == ["gif"]  # gif -> png is not about the video any more
    assert plan("mp4", edges, no_sound_or_png)["mp3"].via == ["mkv"]  # the default is unchanged


def test_silent_video_offers_no_audio_targets(tmp_path, capsys):
    ffmpeg = tools.ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg is not available")
    src = tmp_path / "silent.mp4"
    lavfi = ["-f", "lavfi", "-i", "testsrc=duration=1:size=96x64:rate=10"]
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *lavfi, "-an", "-pix_fmt", "yuv420p", str(src)], check=True
    )
    assert cli.main([str(src), "--list"]) == 0
    listed = {line.split()[0] for line in capsys.readouterr().out.splitlines() if line.startswith("  ")}
    assert "mkv" in listed and not listed & {"mp3", "wav", "srt", "txt"}
    assert cli.main([str(src), "--to", "mp3", "-o", str(tmp_path / "out")]) == 2


def test_truetype_font_is_not_offered_as_otf(tmp_path, capsys):
    src = make_font(tmp_path / "sans.ttf")
    assert cli.main([str(src), "--list"]) == 0
    listed = {line.split()[0] for line in capsys.readouterr().out.splitlines() if line.startswith("  ")}
    assert "woff" in listed and "otf" not in listed


# format detection ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, content, expected",
    [
        ("setup.cfg", "[metadata]\nname = demo\nversion = 1\n", "ini"),
        (".gitconfig", '[user]\n\tname = Ana\n[remote "origin"]\n\turl = x\n', "ini"),
        ("app.unknownext", "; settings\n[main]\n# comment\nkey: value\n", "ini"),
        ("app.log.1", "[2026-10-15 12:00:01] INFO started\n[2026-10-15 12:00:02] INFO done\n", "txt"),
        ("notes.unknownext", "{not json at all}\n", "txt"),
        ("data.unknownext", '{"a": [1, 2]}', "json"),
        ("rows.unknownext", '{"a": 1}\n{"a": 2}\n', "jsonl"),
        ("big.unknownext", json.dumps({"k": ["x" * 50] * 200}, indent=1), "json"),  # only its first 4 KB are read
        ("long.unknownext", json.dumps({"k": "y" * 9000}), "json"),
    ],
)
def test_text_sniffing(tmp_path, name, content, expected):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    assert formats.detect(path) == expected


def tar_bytes() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("hello.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    return buffer.getvalue()


@pytest.mark.parametrize("compress, fmt", [(gzip.compress, "tgz"), (bz2.compress, "tbz2"), (lzma.compress, "txz")])
def test_compressed_single_file_is_not_a_tar(tmp_path, compress, fmt):
    single = tmp_path / "table.csv.packed"
    single.write_bytes(compress(b"a,b\n1,2\n"))
    archive = tmp_path / "bundle.packed"
    archive.write_bytes(compress(tar_bytes()))
    assert formats.detect(single) is None
    assert formats.detect(archive) == fmt


def test_gzipped_csv_is_reported_as_unknown(tmp_path, capsys):
    src = tmp_path / "table.csv.gz"
    src.write_bytes(gzip.compress(b"a,b\n1,2\n"))
    assert cli.main([str(src), "--list"]) == 2
    assert "--from" in capsys.readouterr().err


@pytest.mark.parametrize(
    "name, packet, expected",
    [
        ("mod.mts", 0, "code"),
        ("mod.cts", 0, "code"),
        ("cam.mts", 192, "ts"),  # AVCHD: 192-byte packets that start with a 4-byte timestamp
        ("cam.ts", 192, "ts"),
        ("clip.mts", 188, "ts"),
        ("disc.m2ts", 192, "ts"),
    ],
)
def test_typescript_or_transport_stream(tmp_path, name, packet, expected):
    path = tmp_path / name
    if packet:
        path.write_bytes((b"\0" * (packet - 188) + b"\x47" + b"\0" * 187) * 4)
    else:
        path.write_text("export const x: number = 1;\n")
    assert formats.detect(path) == expected


# messages ----------------------------------------------------------------------------------------


def test_emoji_codes_are_printed_as_is(capsys):
    cli.error("Stream map '0:a:0' matches no streams")
    cli.console.print("photo:smile:.png")
    captured = capsys.readouterr()
    assert "'0:a:0'" in captured.err and "photo:smile:.png" in captured.out


def test_damaged_file_is_not_blamed_on_missing_tools(tmp_path, capsys):
    if not tools.ffmpeg():
        pytest.skip("FFmpeg is not available")
    src = tmp_path / "fake.mp4"
    src.write_text("hello world")
    assert cli.main([str(src), "--list"]) == 1
    err = capsys.readouterr().err
    assert "damaged" in err and "--from" in err and "--doctor" not in err


def test_missing_tools_still_point_to_doctor(tmp_path, monkeypatch, capsys):
    src = tmp_path / "data.json"
    src.write_text('{"a": 1}')
    monkeypatch.setattr(cli, "all_edges", lambda: [])
    assert cli.main([str(src), "--list"]) == 1
    assert "--doctor" in capsys.readouterr().err


@pytest.mark.parametrize("lang", ["en", "es"])
def test_new_messages_are_translated(lang):
    for key in ("file.damaged", "file.already"):
        assert key in i18n.MESSAGES[lang]


# paper size --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"LANG": "en_US.UTF-8"}, "us-letter"),
        ({"LANG": "en_US.UTF-8", "LC_PAPER": "es_ES.UTF-8"}, "a4"),
        ({"LANG": "C.UTF-8", "LC_PAPER": "en_US.UTF-8"}, "us-letter"),
        ({"LANG": "es_MX.UTF-8", "TRANSCRIPT_LANG": "en"}, "us-letter"),
        ({"LANG": "en_GB.UTF-8", "LC_MESSAGES": "en_US.UTF-8", "TRANSCRIPT_LANG": "en"}, "a4"),
        ({"LC_ALL": "de_DE.UTF-8", "LC_PAPER": "en_US.UTF-8"}, "a4"),
        ({}, "a4"),
    ],
)
def test_paper_size_follows_the_region(monkeypatch, env, expected):
    monkeypatch.setattr(sys, "platform", "linux")
    for var in ("LC_ALL", "LC_PAPER", "LC_MESSAGES", "LANG", "LANGUAGE", "TRANSCRIPT_LANG"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert i18n.paper_size() == expected


@pytest.mark.skipif(sys.platform != "win32", reason="Windows regional settings")
def test_paper_size_on_windows():
    assert i18n.paper_size() in ("a4", "us-letter")


# paths -------------------------------------------------------------------------------------------


def test_wildcards_in_a_folder_with_brackets(tmp_path):
    folder = tmp_path / "Photos [2024]"
    other = tmp_path / "Photos 2"  # what '[2024]' means as a pattern
    folder.mkdir()
    other.mkdir()
    for path in (folder / "a.json", folder / "b.json", other / "other.json"):
        path.write_text("{}")
    assert cli.expand([folder / "*.json"]) == [folder / "a.json", folder / "b.json"]
    assert cli.expand([Path(str(tmp_path / "Photos 2*") + os.sep + "*.json")]) == [other / "other.json"]


def test_output_folder_gets_the_quote_cleanup(tmp_path):
    src = tmp_path / "one.json"
    src.write_text('{"n": 1}')
    out = tmp_path / "Out Dir"
    assert cli.main([str(src), "--to", "yaml", "-o", str(out) + '"']) == 0
    assert (out / "one.yaml").is_file()


def test_symlinked_input_keeps_its_name_and_folder(tmp_path):
    real = tmp_path / "samples" / "photo.json"
    real.parent.mkdir()
    real.write_text('{"a": 1}')
    link = tmp_path / "linkdir" / "mylink.json"
    link.parent.mkdir()
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available")
    assert cli.main([str(link), "--to", "yaml"]) == 0
    assert (link.parent / "mylink.yaml").is_file()
    assert not (real.parent / "photo.yaml").exists()


def test_parent_folder_argument_still_has_a_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path / "..")
    assert cli.absolute(Path(tmp_path.name) / "..") == tmp_path.parent.resolve()
    assert cli.absolute(Path(".")).name == tmp_path.parent.resolve().name


# batches -----------------------------------------------------------------------------------------


def test_batch_skips_files_already_in_the_target_format(tmp_path, capsys):
    first = tmp_path / "one.json"
    second = tmp_path / "two.yaml"
    first.write_text('{"n": 1}')
    second.write_text("n: 2\n")
    assert cli.main([str(first), str(second), "--to", "json"]) == 0
    assert json.loads((tmp_path / "two.json").read_text()) == {"n": 2}
    assert "one.json" in capsys.readouterr().err
    assert cli.main([str(first), "--to", "json"]) == 0
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["one.json", "two.json", "two.yaml"]


# signals -----------------------------------------------------------------------------------------


@pytest.fixture
def restore_signals():
    names = [n for n in ("SIGTERM", "SIGHUP", "SIGQUIT", "SIGBREAK") if hasattr(signal, n)]
    saved = {n: signal.getsignal(getattr(signal, n)) for n in names}
    yield
    for name, handler in saved.items():
        signal.signal(getattr(signal, name), handler)


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="POSIX signals")
def test_hangup_and_quit_unwind_the_stack(restore_signals):
    signal.signal(signal.SIGQUIT, signal.SIG_DFL)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)  # as under 'nohup'
    cli._prepare_terminal()
    assert signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
    handler = signal.getsignal(signal.SIGQUIT)
    with pytest.raises(SystemExit) as exc:
        handler(signal.SIGQUIT, None)
    assert exc.value.code == 128 + signal.SIGQUIT


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="POSIX signals")
@pytest.mark.parametrize("name", ["SIGHUP", "SIGQUIT"])
def test_closing_the_terminal_removes_the_workspace(tmp_path, name):
    base = tmp_path / "signal_ws"
    script = (
        "import time\n"
        "from transcript.cli import _prepare_terminal\n"
        "from transcript.engine import Workspace\n"
        "_prepare_terminal()\n"
        "with Workspace() as ws:\n"
        "    print(ws, flush=True)\n"
        "    time.sleep(60)\n"
    )
    env = {**os.environ, "TRANSCRIPT_TMPDIR": str(base)}
    env.pop("PYTHONSTARTUP", None)
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, env=env)
    try:
        workspace = Path(proc.stdout.readline().strip())
        assert workspace.name.startswith("transcript-") and workspace.is_dir()
        proc.send_signal(getattr(signal, name))
        assert proc.wait(timeout=30) == 128 + getattr(signal, name)
    finally:
        proc.kill()
        proc.stdout.close()
    assert list(base.iterdir()) == []


def test_menu_search_ignores_the_route_and_the_headings():
    from transcript.ui import MenuTitle

    title = MenuTitle("PDF                .pdf     via TXT", "PDF                .pdf")
    assert str(title) == "PDF                .pdf     via TXT"  # what the menu shows
    assert "txt" not in title.lower()  # what type-to-filter searches
    assert "pdf" in title.lower()
    assert f"{title}".endswith("via TXT")  # questionary renders it with "{}".format()
