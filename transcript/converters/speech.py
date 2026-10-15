"""Speech to text: transcribe audio and video into TXT, SRT or VTT with faster-whisper."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .. import formats, i18n
from .base import ConversionError, Converter, Edge

TARGETS = ("txt", "srt", "vtt")


def default_model() -> str:
    return os.environ.get("TRANSCRIPT_WHISPER_MODEL") or "small"


class SpeechConverter(Converter):
    name = "faster-whisper"
    hint = "pipx inject transcript-cli faster-whisper  ·  or: pip install transcript-cli[speech]"

    def available(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def details(self) -> str:
        return f"model: {default_model()} (change it with --model)"

    def edges(self):
        sources = formats.ids_in("audio") + formats.ids_in("video")
        # Slow and approximate: only used when nothing better is available.
        return [self.edge(src, dst, cost=5.0) for src in sources for dst in TARGETS]

    def accepts(self, src: Path, edge: Edge, ctx) -> bool:
        from .media import probe

        try:
            return bool(probe(str(src)).audio)
        except Exception:
            return True

    def convert(self, src: Path, dst: Path, edge: Edge, ctx) -> Path:
        from faster_whisper import WhisperModel

        model_name = ctx.options.model or default_model()
        ctx.reporter.log(i18n.t("speech.loading", model=model_name))
        try:
            model = WhisperModel(model_name, device="auto", compute_type="int8")
        except Exception as exc:
            raise ConversionError(
                f"cannot load the speech model '{model_name}' (it is downloaded from huggingface.co the first time): {exc}"
            ) from exc
        try:
            segments, info = model.transcribe(str(src), language=ctx.options.lang, vad_filter=True, beam_size=5)
            collected = []
            for segment in segments:
                collected.append(segment)
                ctx.progress(segment.end, info.duration)
        except Exception as exc:
            raise ConversionError(f"speech recognition failed: {exc}") from exc

        if edge.dst == "txt":
            text = "\n".join(s.text.strip() for s in collected if s.text.strip())
            dst.write_text(text + "\n", encoding="utf-8")
            return dst

        import pysubs2

        subs = pysubs2.SSAFile()
        for segment in collected:
            if segment.text.strip():
                start, end = int(segment.start * 1000), int(segment.end * 1000)
                subs.append(pysubs2.SSAEvent(start=start, end=end, text=segment.text.strip()))
        subs.save(str(dst), format_=edge.dst, encoding="utf-8")
        return dst
