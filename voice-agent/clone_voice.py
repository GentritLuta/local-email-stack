# -*- coding: utf-8 -*-
"""clone_voice.py - local voice cloning with Chatterbox (Resemble AI, open source).

Cheapest cutting-edge path: runs on the RTX GPU, clones a voice from a short clean
reference clip (~10-30s), zero per-call TTS cost. Used two ways:
  1. CLI smoke test:   python clone_voice.py "hello, this is a test" out.wav
  2. Imported by agent.py's ChatterboxTTSService for the live call pipeline.

Model + reference are loaded ONCE and reused (loading per-utterance would blow
the real-time budget). Requires: pip install chatterbox-tts torchaudio, CUDA GPU.
"""
from __future__ import annotations

import os
from functools import lru_cache

_REFERENCE = os.getenv("CLONE_REFERENCE_WAV", "voice-agent/voices/agent_sample.wav")


@lru_cache(maxsize=1)
def _model():
    # Imported lazily so the module is importable (and unit-testable) on a machine
    # without CUDA/Chatterbox installed. The heavy load happens on first synth call.
    import torch
    from chatterbox.tts import ChatterboxTTS
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        print("[clone_voice] WARNING: no CUDA - Chatterbox on CPU is far too slow "
              "for a live call. Bring the RTX box online for real-time.")
    return ChatterboxTTS.from_pretrained(device=device)


def synth(text: str, reference_wav: str | None = None):
    """Return (waveform_tensor, sample_rate) for `text` in the cloned voice."""
    model = _model()
    ref = reference_wav or _REFERENCE
    if not os.path.exists(ref):
        raise FileNotFoundError(
            f"reference voice sample not found: {ref}. Drop a 10-30s clean clip of "
            f"the voice to clone there (set CLONE_REFERENCE_WAV to change the path).")
    wav = model.generate(text, audio_prompt_path=ref)
    return wav, model.sr


def synth_to_file(text: str, out_path: str, reference_wav: str | None = None) -> str:
    import torchaudio as ta
    wav, sr = synth(text, reference_wav)
    ta.save(out_path, wav, sr)
    return out_path


if __name__ == "__main__":
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "Hi, this is a quick test of the cloned voice."
    out = sys.argv[2] if len(sys.argv) > 2 else "clone_test.wav"
    print("synthesizing...")
    print("wrote", synth_to_file(text, out))
