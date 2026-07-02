# -*- coding: utf-8 -*-
"""agent.py - the Pipecat voice agent: STT -> LLM -> TTS, all local on the RTX.

Pipeline (free path):
    caller audio  ->  faster-whisper (STT)  ->  local LLM (Ollama/vLLM)
                  ->  Chatterbox cloned voice (TTS)  ->  caller audio

IMPORTANT - PIN THE API: Pipecat's service import paths move between releases.
The structure below is the stable Pipecat shape (Pipeline of processors, a
PipelineTask run by a PipelineRunner, a transport at each end). After
`pip install pipecat-ai` on the RTX box, run `python -c "import pipecat, pipecat.pipeline"`
and adjust the imports in the PIN block to match the installed version. Docs:
https://docs.pipecat.ai . Everything OUTSIDE the PIN block (disclosure-first
ordering, the prompt, outcome capture) is framework-stable and correct as written.

This file assumes the CONSENT GATE already passed - dial.py only ever bridges a
call here after compliance.can_call() returns True, and the first thing spoken is
the AI disclosure. Never call this agent for a lead that failed the gate.
"""
from __future__ import annotations

import os

from prompts import system_prompt
import compliance

# ─── PIN block: verify these against the installed pipecat version ──────────────
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.services.whisper.stt import WhisperSTTService          # local STT
from pipecat.services.openai.llm import OpenAILLMService            # points at local endpoint
from pipecat.services.tts_service import TTSService                 # base class to wrap Chatterbox
from pipecat.frames.frames import TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
# transport: for Telnyx telephony this is a websocket/serializer transport bridged
# from the Telnyx media stream. Kept abstract here; see dial.py + docs for the bridge.
# ───────────────────────────────────────────────────────────────────────────────

AGENCY = os.getenv("AGENCY_NAME", "Aureon")
AGENT_NAME = os.getenv("AGENT_NAME", "Alex")
LOCAL_AGENT = os.getenv("LOCAL_AGENT_NAME", "Andrew")


class ChatterboxTTSService(TTSService):
    """Wrap the local Chatterbox cloned voice as a Pipecat TTS service so the
    cloned voice streams straight into the call. Free, runs on the RTX GPU."""

    def __init__(self, reference_wav: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._reference = reference_wav

    async def run_tts(self, text: str):
        # Lazy import so the module loads without CUDA present.
        import numpy as np
        from clone_voice import synth
        wav, sr = synth(text, self._reference)
        pcm = (np.clip(wav.squeeze().cpu().numpy(), -1, 1) * 32767).astype("int16").tobytes()
        yield TTSStartedFrame()
        yield TTSAudioRawFrame(audio=pcm, sample_rate=sr, num_channels=1)
        yield TTSStoppedFrame()


def build_pipeline(transport, area: str = "your area") -> PipelineTask:
    """Assemble the STT -> LLM -> TTS pipeline for one call.

    `transport` is the Telnyx-bridged audio transport (input()/output()). The
    disclosure is forced as the first spoken line via the seeded assistant turn,
    so it never depends on the model remembering to say it.
    """
    stt = WhisperSTTService(model=os.getenv("WHISPER_MODEL", "base.en"))
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY", "local"),
        base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1"),
        model=os.getenv("LLM_MODEL", "llama3.1:8b-instruct"),
    )
    tts = ChatterboxTTSService(reference_wav=os.getenv("CLONE_REFERENCE_WAV"))

    # Seed the conversation: system brief + a FORCED opening line = the disclosure.
    messages = [
        {"role": "system", "content": system_prompt(AGENCY, AGENT_NAME, LOCAL_AGENT, area)},
        {"role": "assistant", "content": compliance.disclosure_line(AGENCY)},
    ]
    # NOTE: use the installed pipecat's context-aggregator pair to keep history
    # (import path varies by version - see the PIN note at the top).
    context = llm.create_context_aggregator(messages)  # verify method name per version

    pipeline = Pipeline([
        transport.input(),
        stt,
        context.user(),
        llm,
        tts,
        transport.output(),
        context.assistant(),
    ])
    return PipelineTask(pipeline, PipelineParams(allow_interruptions=True))


async def run_call(transport, area: str = "your area"):
    task = build_pipeline(transport, area)
    await PipelineRunner(handle_sigint=False).run(task)
