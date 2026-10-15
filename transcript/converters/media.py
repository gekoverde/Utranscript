"""Audio and video with FFmpeg."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .. import formats, tools
from .base import ConversionError, Converter, Edge

Encoders = tuple[tuple[str, tuple[str, ...]], ...]  # (encoder, arguments) by preference


@dataclass(frozen=True)
class Target:
    video: Encoders = ()
    audio: Encoders = ()
    copy_video: frozenset[str] | None = frozenset()  # codecs that can be copied as is; None = any
    copy_audio: frozenset[str] | None = frozenset()
    extra: tuple[str, ...] = ()


H264: Encoders = (
    ("libx264", ("-preset", "medium", "-crf", "23")),
    ("libopenh264", ("-b:v", "4M")),
    ("h264_mf", ("-b:v", "4M")),
    ("mpeg4", ("-q:v", "3")),
)
AAC: Encoders = (("aac", ("-b:a", "160k")), ("libfdk_aac", ("-b:a", "160k")))
AAC_HQ: Encoders = (("aac", ("-b:a", "192k")), ("libfdk_aac", ("-b:a", "192k")))
VORBIS: Encoders = (("libvorbis", ("-q:a", "5")), ("vorbis", ("-q:a", "5", "-strict", "-2", "-ac", "2")))
OPUS: Encoders = (("libopus", ("-b:a", "128k")), ("opus", ("-b:a", "128k", "-strict", "-2", "-ar", "48000", "-ac", "2")))
MP4_AUDIO = frozenset({"aac", "mp3", "alac", "ac3"})


def _set(*names: str) -> frozenset[str]:
    return frozenset(names)


AUDIO_TARGETS: dict[str, Target] = {
    "mp3": Target(audio=(("libmp3lame", ("-q:a", "2")),), copy_audio=_set("mp3")),
    "wav": Target(audio=(("pcm_s16le", ()),), copy_audio=_set("pcm_s16le")),
    "flac": Target(audio=(("flac", ()),), copy_audio=_set("flac")),
    "m4a": Target(audio=AAC_HQ, copy_audio=_set("aac", "alac"), extra=("-movflags", "+faststart")),
    "aac": Target(audio=AAC_HQ, copy_audio=_set("aac")),
    "ogg": Target(audio=VORBIS, copy_audio=_set("vorbis")),
    "opus": Target(audio=OPUS, copy_audio=_set("opus")),
    "wma": Target(audio=(("wmav2", ("-b:a", "192k")),), copy_audio=_set("wmav1", "wmav2")),
    "aiff": Target(audio=(("pcm_s16be", ()),), copy_audio=_set("pcm_s16be")),
    "ac3": Target(audio=(("ac3", ("-b:a", "384k")),), copy_audio=_set("ac3")),
    "mka": Target(audio=(("flac", ()),), copy_audio=None),
}

VIDEO_TARGETS: dict[str, Target] = {
    "mp4": Target(H264, AAC, _set("h264", "hevc", "mpeg4", "av1"), MP4_AUDIO, ("-movflags", "+faststart")),
    "m4v": Target(H264, AAC, _set("h264", "hevc", "mpeg4"), MP4_AUDIO, ("-movflags", "+faststart")),
    "mov": Target(
        H264,
        AAC,
        _set("h264", "hevc", "mpeg4", "prores", "mjpeg"),
        _set("aac", "alac", "mp3", "pcm_s16le", "pcm_s24le"),
    ),
    "mkv": Target(H264, AAC, None, None),
    "webm": Target(
        (
            ("libvpx-vp9", ("-crf", "32", "-b:v", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4")),
            ("libvpx", ("-crf", "10", "-b:v", "2M")),
            ("libsvtav1", ("-crf", "35")),
            ("libaom-av1", ("-crf", "32", "-b:v", "0", "-cpu-used", "6")),
        ),
        OPUS + VORBIS,
        _set("vp8", "vp9", "av1"),
        _set("opus", "vorbis"),
    ),
    "avi": Target(
        (("libxvid", ("-q:v", "4")), ("mpeg4", ("-q:v", "4", "-vtag", "xvid"))),
        (("libmp3lame", ("-q:a", "4")), ("ac3", ("-b:a", "192k"))),
        _set("mpeg4", "msmpeg4v3", "mjpeg"),
        _set("mp3", "ac3", "pcm_s16le"),
    ),
    "wmv": Target(
        (("wmv2", ("-b:v", "4M")),),
        (("wmav2", ("-b:a", "192k")),),
        _set("wmv1", "wmv2", "wmv3", "vc1"),
        _set("wmav1", "wmav2", "wmapro"),
    ),
    "flv": Target(H264, (("aac", ("-b:a", "160k", "-ar", "44100")),), _set("h264", "flv1"), _set("aac", "mp3")),
    "mpeg": Target(
        (("mpeg2video", ("-q:v", "3")),),
        (("mp2", ("-b:a", "192k")),),
        _set("mpeg1video", "mpeg2video"),
        _set("mp2", "mp3", "ac3"),
        ("-f", "dvd"),
    ),
    "ogv": Target((("libtheora", ("-q:v", "7")),), VORBIS, _set("theora"), _set("vorbis", "opus")),
    "3gp": Target(
        (("libx264", ("-preset", "medium", "-crf", "26", "-profile:v", "baseline")),) + H264[1:],
        (("aac", ("-b:a", "96k")),),
        _set("h264", "h263", "mpeg4"),
        _set("aac", "amr_nb"),
    ),
    "ts": Target(H264, AAC, _set("h264", "hevc", "mpeg2video"), _set("aac", "mp3", "ac3", "mp2"), ("-f", "mpegts")),
}

GIF_FILTER = (
    "fps=12,scale='min(720,iw)':-1:flags=lanczos,split[a][b];"
    "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
)
EVEN_SIZE = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


@dataclass(frozen=True)
class Probe:
    duration: float | None
    video: tuple[str, ...]
    audio: tuple[str, ...]
    subtitles: tuple[str, ...]


@cache
def encoders() -> frozenset[str]:
    out = tools.run([tools.ffmpeg(), "-hide_banner", "-encoders"]).stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS" and parts[1] != "=":
            names.add(parts[1])
    return frozenset(names)


@cache
def probe(path: str) -> Probe:
    """Read duration and stream codecs from the FFmpeg banner."""
    proc = subprocess.run(
        [tools.ffmpeg(), "-hide_banner", "-nostdin", "-i", path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    text = proc.stderr
    duration = None
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match:
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    streams: dict[str, list[str]] = {"Video": [], "Audio": [], "Subtitle": []}
    for match in re.finditer(r"Stream #\d+:\d+.*?: (Video|Audio|Subtitle): ([\w-]+)(.*)", text):
        kind, codec, rest = match.groups()
        if kind == "Video" and "attached pic" in rest:
            continue  # cover art, not a real video
        streams[kind].append(codec)
    return Probe(duration, tuple(streams["Video"]), tuple(streams["Audio"]), tuple(streams["Subtitle"]))


def _pick(choices: Encoders) -> tuple[str, tuple[str, ...]] | None:
    available = encoders()
    for name, args in choices:
        if name in available:
            return name, args
    return None


class FFmpegConverter(Converter):
    name = "FFmpeg"
    hint = "pip install imageio-ffmpeg  ·  or install FFmpeg (winget install Gyan.FFmpeg / sudo apt install ffmpeg)"

    def available(self) -> bool:
        return tools.ffmpeg() is not None

    def details(self) -> str:
        exe = tools.ffmpeg()
        first = tools.run([exe, "-hide_banner", "-version"]).stdout.split("\n", 1)[0]
        version = first.split(" ")[2] if first.startswith("ffmpeg version") else ""
        return f"FFmpeg {version} · {exe}"

    def edges(self):
        audio_targets = [t for t, spec in AUDIO_TARGETS.items() if _pick(spec.audio)]
        video_targets = [t for t, spec in VIDEO_TARGETS.items() if _pick(spec.video)]
        audio_sources = formats.ids_in("audio") + formats.ids_in("video")
        edges = self.matrix(audio_sources, audio_targets)
        edges += self.matrix(formats.ids_in("video"), video_targets)
        # Animated GIFs become silent videos.
        edges += [self.edge("gif", fmt, terminal=True, first_only=True) for fmt in video_targets]
        if "gif" in encoders():
            edges += [self.edge(v, "gif", terminal=True) for v in formats.ids_in("video")]
        return edges

    def accepts(self, src: Path, edge: Edge, ctx) -> bool:
        try:
            info = probe(str(src))
        except Exception:
            return True
        if edge.dst in AUDIO_TARGETS:
            return bool(info.audio)
        if edge.src != "gif":
            return bool(info.video)
        return True

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        info = probe(str(src))
        if edge.dst == "gif":
            attempts = [["-map", "0:v:0", "-an", "-sn", "-vf", GIF_FILTER, "-loop", "0"]]
        elif edge.dst in AUDIO_TARGETS:
            attempts = self._audio_attempts(info, AUDIO_TARGETS[edge.dst])
        else:
            attempts = self._video_attempts(info, VIDEO_TARGETS[edge.dst], edge.dst)
        for index, args in enumerate(attempts):
            try:
                self._run(src, dst, args, info.duration, ctx)
                return dst
            except ConversionError as exc:
                if index == len(attempts) - 1:
                    raise
                ctx.log(f"stream copy not possible, re-encoding ({exc})")
                dst.unlink(missing_ok=True)
        return dst

    @staticmethod
    def _audio_attempts(info: Probe, spec: Target) -> list[list[str]]:
        base = ["-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "0"]
        attempts = []
        if info.audio and (spec.copy_audio is None or info.audio[0] in spec.copy_audio):
            attempts.append(base + ["-c:a", "copy", *spec.extra])
        encoder = _pick(spec.audio)
        if encoder is None:
            raise ConversionError("no suitable audio encoder in this FFmpeg build")
        attempts.append(base + ["-c:a", encoder[0], *encoder[1], *spec.extra])
        return attempts

    @staticmethod
    def _video_attempts(info: Probe, spec: Target, target: str) -> list[list[str]]:
        attempts = []
        video_ok = info.video and (spec.copy_video is None or info.video[0] in spec.copy_video)
        audio_ok = spec.copy_audio is None or all(a in spec.copy_audio for a in info.audio)
        if video_ok and audio_ok:
            copy = ["-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-map_metadata", "0", *spec.extra]
            if target == "mkv" and info.subtitles:
                attempts.append(copy[:4] + ["-map", "0:s?"] + copy[4:])
            attempts.append(copy[:4] + ["-sn"] + copy[4:])
        video = _pick(spec.video)
        if video is None:
            raise ConversionError("no suitable video encoder in this FFmpeg build")
        encode = ["-map", "0:v:0", "-map", "0:a?", "-c:v", video[0], *video[1], "-pix_fmt", "yuv420p", "-vf", EVEN_SIZE]
        audio = _pick(spec.audio)
        if info.audio and audio:
            encode += ["-c:a", audio[0], *audio[1]]
        else:
            encode.append("-an")
        encode += ["-sn", "-map_metadata", "0", *spec.extra]
        attempts.append(encode)
        return attempts

    @staticmethod
    def _run(src: Path, dst: Path, args: list[str], duration: float | None, ctx) -> None:
        cmd = [tools.ffmpeg(), "-hide_banner", "-nostdin", "-y", "-i", str(src), *args]
        cmd += ["-progress", "pipe:1", "-nostats", "-loglevel", "error", str(dst)]
        ctx.log(" ".join(cmd))
        errors = ctx.scratch("ffmpeg") / "stderr.txt"
        with open(errors, "w+", encoding="utf-8", errors="replace") as err:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8", errors="replace"
            )
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    key, _, value = line.strip().partition("=")
                    if key in ("out_time_us", "out_time_ms") and value.isdigit():
                        ctx.progress(int(value) / 1_000_000, duration)
                code = proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
            if code != 0:
                err.seek(0)
                raise ConversionError(f"FFmpeg: {tools.tail(err.read(), 5)}")
