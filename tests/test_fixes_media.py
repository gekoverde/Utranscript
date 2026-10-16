"""Regression tests for subtitles (MicroDVD, SAMI, VobSub), audio/video targets and speech devices."""

from __future__ import annotations

import re
import subprocess
import sys
import time
import types
from collections import namedtuple
from pathlib import Path

import pytest
from conftest import make_media

from transcript import tools
from transcript.cli import main
from transcript.converters import media
from transcript.converters.base import ConversionError
from transcript.converters.speech import SpeechConverter
from transcript.converters.subtitles import SubtitleConverter
from transcript.engine import Context, Options, Reporter, Workspace


def printed(capsys) -> str:
    captured = capsys.readouterr()
    return (captured.out + captured.err).replace("\n", "")


def banner(path: Path) -> str:
    """What FFmpeg says about a file (ffprobe is not bundled with imageio-ffmpeg)."""
    cmd = [tools.ffmpeg(), "-hide_banner", "-i", str(path)]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr


def ffmpeg(*args: str) -> None:
    if not tools.ffmpeg():
        pytest.skip("FFmpeg is not available")
    subprocess.run([tools.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


TONE = ("-f", "lavfi", "-i", "sine=frequency=440:duration=1")
PICTURE = ("-f", "lavfi", "-i", "testsrc=duration=1:size=96x64:rate=10")


def needs_encoder(name: str) -> None:
    if not tools.ffmpeg() or name not in media.encoders():
        pytest.skip(f"this FFmpeg build has no {name} encoder")


# subtitles ---------------------------------------------------------------------------------


def test_microdvd_frame_rate_declaration_is_honoured(samples, convert):
    src = samples / "declared.sub"
    src.write_text("{1}{1}25.000\n{250}{300}Hello\n{500}{550}World\n", encoding="utf-8")
    srt = convert(src, "srt").read_text(encoding="utf-8")
    assert "25.000" not in srt
    assert "00:00:10,000 --> 00:00:12,000\nHello" in srt
    assert "00:00:20,000 --> 00:00:22,000\nWorld" in srt


def test_microdvd_without_declaration_uses_the_default_frame_rate(samples, convert):
    src = samples / "plain.sub"
    src.write_text("{240}{288}Hello\n", encoding="utf-8")
    assert "00:00:10,010 --> 00:00:12,012\nHello" in convert(src, "srt").read_text(encoding="utf-8")


def test_microdvd_round_trip_has_no_bogus_frame_rate_cue(samples, convert, tmp_path):
    src = samples / "a.srt"
    src.write_text("1\n00:00:10,000 --> 00:00:12,000\nHello\n", encoding="utf-8")
    sub = convert(src, "sub")
    # pysubs2 writes "{1}{1}23.976" since 1.9 and "{0}{0}23.976" before.
    assert re.match(r"\{[01]\}\{[01]\}23\.976", sub.read_text(encoding="utf-8"))
    back = samples / "back.sub"
    back.write_bytes(sub.read_bytes())
    assert convert(back, "txt").read_text(encoding="utf-8") == "Hello\n"


@pytest.mark.parametrize("declaration", ["{0}{0}25.000", "{1}{1}25"])
def test_microdvd_declared_frame_rate_in_any_form(samples, convert, declaration):
    src = samples / "movie.sub"
    src.write_text(f"{declaration}\n{{250}}{{300}}Hello\n", encoding="utf-8")
    srt = convert(src, "srt").read_text(encoding="utf-8")
    assert "00:00:10,000 --> 00:00:12,000" in srt
    assert "25" not in srt.split("-->")[0].splitlines()[-1].replace("00:00:10,000", "")
    assert srt.count("-->") == 1


def test_sami_is_read_but_never_offered_as_a_target():
    edges = list(SubtitleConverter().edges())
    assert not any(e.dst == "sami" for e in edges)
    assert any(e.src == "sami" and e.dst == "srt" for e in edges)
    assert any(e.dst == "ttml" for e in edges)


def test_vobsub_is_explained(samples, tmp_path, capsys):
    src = samples / "movie.sub"
    src.write_bytes(b"\x00\x00\x01\xba" + bytes(range(256)) * 40)
    assert main([str(src), "--to", "srt", "-o", str(tmp_path / "out")]) == 1
    assert "VobSub" in printed(capsys)
    assert not (tmp_path / "out" / "movie.srt").exists()


def test_subtitles_without_cues_are_an_error(samples, tmp_path, capsys):
    src = samples / "empty.srt"
    src.write_text("this is not a subtitle file\n", encoding="utf-8")
    assert main([str(src), "--to", "vtt", "-o", str(tmp_path / "out")]) == 1
    assert "no subtitles found" in printed(capsys)


# audio and video ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "codec, details, sample",
    [
        ("flac", ", 96000 Hz, stereo, s32 (24 bit)", "s24"),
        ("pcm_s24le", " ([1][0][0][0] / 0x0001), 48000 Hz, 2 channels, s32 (24 bit), 2304 kb/s", "s24"),
        ("pcm_s32le", " ([1][0][0][0] / 0x0001), 48000 Hz, 2 channels, s32, 3072 kb/s", "s32"),
        ("pcm_f32le", " ([3][0][0][0] / 0x0003), 48000 Hz, stereo, flt, 3072 kb/s (default)", "f32"),
        ("alac", " (alac / 0x63616C61), 44100 Hz, stereo, s32p (24 bit), 2116 kb/s", "s24"),
        ("pcm_u8", " ([1][0][0][0] / 0x0001), 8000 Hz, mono, u8, 64 kb/s", "s16"),
        ("flac", ", 44100 Hz, stereo, s16", "s16"),
        ("aac", " (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 128 kb/s", "s16"),
        ("mp3", ", 44100 Hz, stereo, fltp, 192 kb/s", "s16"),
        ("dts", " (DTS-HD MA), 48000 Hz, 5.1(side), s32p (24 bit)", "s24"),
    ],
)
def test_sample_type_from_the_banner(codec, details, sample):
    assert media._sample(codec, details) == sample


@pytest.mark.parametrize("target, codec", [("wav", "pcm_s24le"), ("aiff", "pcm_s24be")])
def test_high_resolution_audio_keeps_its_bit_depth(samples, convert, target, codec):
    src = samples / "hires.flac"
    ffmpeg(*TONE, "-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24", str(src))
    assert media.probe(str(src)).sample == "s24"
    assert media.probe(str(convert(src, target))).audio == (codec,)


def test_float_audio_stays_float_and_lossy_audio_stays_16_bit(samples, convert):
    floating = samples / "float.wav"
    ffmpeg(*TONE, "-c:a", "pcm_f32le", str(floating))
    assert media.probe(str(convert(floating, "aiff"))).audio == ("pcm_f32be",)
    needs_encoder("libmp3lame")
    mp3 = convert(make_media(samples / "tone.wav", video=False), "mp3")
    lossy = samples / "lossy.mp3"
    lossy.write_bytes(mp3.read_bytes())
    assert media.probe(str(convert(lossy, "wav"))).audio == ("pcm_s16le",)


def test_compatible_pcm_is_copied():
    pcm24 = media.Probe(1.0, (), ("pcm_s24le",), (), "s24")
    attempts = media.FFmpegConverter._audio_attempts(pcm24, media.AUDIO_TARGETS["wav"])
    assert attempts[0][-1] == "copy"
    assert attempts[1][attempts[1].index("-c:a") + 1] == "pcm_s24le"


def test_wma_and_wmv_downmix_to_stereo(samples, convert):
    six = samples / "six.wav"
    ffmpeg(*TONE, "-ac", "6", str(six))
    assert "stereo" in banner(convert(six, "wma"))
    needs_encoder("wmv2")
    clip = samples / "surround.mkv"
    ffmpeg(*PICTURE, *TONE, "-ac", "6", "-c:a", "flac", "-shortest", str(clip))
    assert "stereo" in banner(convert(clip, "wmv"))


def test_hevc_copy_into_mp4_gets_the_hvc1_tag(samples, convert):
    needs_encoder("libx265")
    src = samples / "hevc.mkv"
    ffmpeg(*PICTURE, "-c:v", "libx265", "-pix_fmt", "yuv420p", "-x265-params", "log-level=error", str(src))
    for target in ("mp4", "mov"):
        info = banner(convert(src, target))
        assert "hevc" in info and "hvc1" in info and "hev1" not in info


def test_hevc_tag_is_added_to_the_copy_attempt(monkeypatch):
    monkeypatch.setattr(media, "encoders", lambda: frozenset({"libx264", "aac"}))
    hevc = media.Probe(1.0, ("hevc",), ("aac",), ())
    for target in ("mp4", "m4v", "mov"):
        copy = media.FFmpegConverter._video_attempts(hevc, media.VIDEO_TARGETS[target], target)[0]
        assert copy[copy.index("-tag:v") + 1] == "hvc1"
    mkv = media.FFmpegConverter._video_attempts(hevc, media.VIDEO_TARGETS["mkv"], "mkv")[0]
    assert "-tag:v" not in mkv


class Interrupting(Reporter):
    def progress(self, done, total=None):
        raise KeyboardInterrupt


def test_interrupted_ffmpeg_is_killed_and_uses_the_workspace_tmp(samples, monkeypatch):
    src = make_media(samples / "long.wav", video=False, seconds=30)
    started: list[tuple[subprocess.Popen, dict]] = []
    killed: list[subprocess.Popen] = []
    real_popen, real_kill = subprocess.Popen, tools.kill_tree

    def popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        started.append((proc, kwargs))
        return proc

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(tools, "kill_tree", lambda proc: (killed.append(proc), real_kill(proc)))
    with Workspace() as workspace:
        ctx = Context(workspace, Options(), Interrupting())
        begin = time.monotonic()
        with pytest.raises(KeyboardInterrupt):  # arealtime makes FFmpeg take 30 s unless it is stopped
            media.FFmpegConverter._run(src, workspace / "out.wav", ["-af", "arealtime", "-c:a", "pcm_s16le"], 30.0, ctx)
        assert time.monotonic() - begin < 20
        # The FFmpeg process (on Windows kill_tree also starts taskkill, after it).
        proc, kwargs = next((p, k) for p, k in started if "taskkill" not in str(p.args))
        assert killed == [proc] and proc.poll() is not None
        assert Path(kwargs["env"]["TMPDIR"]).is_relative_to(workspace)
        assert all(kwargs.get(key) == value for key, value in tools.spawn_options().items())


def test_failed_ffmpeg_reports_its_error(samples):
    src = samples / "broken.mp3"
    src.write_bytes(b"not audio at all" * 10)
    if not tools.ffmpeg():
        pytest.skip("FFmpeg is not available")
    with Workspace() as workspace:
        ctx = Context(workspace, Options(), Reporter())
        with pytest.raises(ConversionError, match="FFmpeg"):
            media.FFmpegConverter._run(src, workspace / "out.wav", ["-c:a", "pcm_s16le"], None, ctx)


# speech ------------------------------------------------------------------------------------

Segment = namedtuple("Segment", "start end text")
Info = namedtuple("Info", "duration")


def fake_whisper(monkeypatch, fail_on: str | None = None, fail_while_iterating: bool = False) -> list[tuple[str, str]]:
    """Replace faster_whisper with a stub; returns the (device, compute_type) of every model created."""
    created: list[tuple[str, str]] = []

    class FakeModel:
        def __init__(self, name, device="auto", compute_type="default", **kwargs):
            created.append((device, compute_type))
            self.device = device
            if device == fail_on and not fail_while_iterating:
                raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")

        def transcribe(self, path, **kwargs):
            def segments():
                if self.device == fail_on:
                    raise RuntimeError("CUDA failed with error out of memory")
                yield Segment(0.0, 1.5, " Hola mundo")

            return segments(), Info(1.5)

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return created


def transcribe(tmp_path: Path, target: str = "txt") -> str:
    converter = SpeechConverter()
    src = tmp_path / "voice.wav"
    src.write_bytes(b"")
    dst = tmp_path / f"voice.{target}"
    with Workspace() as workspace:
        ctx = Context(workspace, Options(model="tiny"), Reporter())
        converter.convert(src, dst, converter.edge("wav", target), ctx)
    return dst.read_text(encoding="utf-8")


def test_speech_uses_the_cpu_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_WHISPER_DEVICE", raising=False)
    created = fake_whisper(monkeypatch)
    assert transcribe(tmp_path) == "Hola mundo\n"
    assert created == [("cpu", "int8")]


@pytest.mark.parametrize("while_iterating", [False, True])
def test_speech_falls_back_to_the_cpu_when_cuda_fails(tmp_path, monkeypatch, while_iterating):
    monkeypatch.setenv("TRANSCRIPT_WHISPER_DEVICE", "cuda")
    created = fake_whisper(monkeypatch, fail_on="cuda", fail_while_iterating=while_iterating)
    assert "Hola mundo" in transcribe(tmp_path, "srt")
    assert [device for device, _ in created] == ["cuda", "cpu"]
    assert created[-1] == ("cpu", "int8")


def test_speech_cpu_failure_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_WHISPER_DEVICE", raising=False)
    created = fake_whisper(monkeypatch, fail_on="cpu")
    with pytest.raises(ConversionError, match="cannot load the speech model"):
        transcribe(tmp_path)
    assert created == [("cpu", "int8")]
