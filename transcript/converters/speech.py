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


def device() -> str:
    """The CPU unless the GPU is asked for: CUDA also needs cuBLAS and cuDNN, which are often missing."""
    return "cuda" if os.environ.get("TRANSCRIPT_WHISPER_DEVICE", "").strip().lower() == "cuda" else "cpu"


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
        model_name = ctx.options.model or default_model()
        ctx.reporter.log(i18n.t("speech.loading", model=model_name))
        wanted = device()
        try:
            collected = self._transcribe(src, model_name, wanted, ctx)
        except ConversionError as exc:
            if wanted == "cpu":
                raise
            ctx.reporter.log(i18n.t("speech.cpu_fallback", "CUDA failed, using the CPU instead ({error})", error=exc))
            collected = self._transcribe(src, model_name, "cpu", ctx)

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

    @staticmethod
    def _transcribe(src: Path, model_name: str, device: str, ctx) -> list:
        from faster_whisper import WhisperModel

        try:
            # "auto" lets CTranslate2 pick a compute type the GPU supports instead of failing.
            model = WhisperModel(model_name, device=device, compute_type="int8" if device == "cpu" else "auto")
        except Exception as exc:
            raise ConversionError(
                f"cannot load the speech model '{model_name}' (it is downloaded from huggingface.co the first time): {exc}"
            ) from exc
        try:  # segments are produced lazily: CUDA errors can also show up while iterating
            segments, info = model.transcribe(str(src), language=ctx.options.lang, vad_filter=True, beam_size=5)
            collected = []
            for segment in segments:
                collected.append(segment)
                ctx.progress(segment.end, info.duration)
            return collected
        except Exception as exc:
            raise ConversionError(f"speech recognition failed: {exc}") from exc
