# voice-agent — cheap, cutting-edge AI voice caller (consent-gated)

An AI phone agent that calls **consented** seller leads in a **cloned voice**, qualifies
them, and books a 15-minute appointment for the local agent (Andrew). Built for the
lowest possible cost: everything runs locally on the RTX box except the phone line.

## Why it's built this way

An AI-cloned voice is an **"artificial voice" under the TCPA** (FCC, 2024). Dialing a US
number with it requires **prior express consent**, a DNC scrub, a recipient-local
8am–9pm window, and an up-front "this is automated" disclosure. Ungated AI cold-calling
is **$500–1,500 per call** with no cap. So the dialer only ever calls leads that carry
consent on record, and the gate ([`compliance.py`](compliance.py)) is not bypassable.

To reach **cold** sellers legally: capture consent first (the funnel checkbox, a text/
landing "yes, call me") which flips them into the callable pool in minutes, or dial them
by hand (the `out/andrew_dialing_sheet.csv` from the FSBO sweep). Do not point this at a
non-consented list.

## The stack (cheapest path = self-hosted on the RTX)

| Layer | Component | Cost |
|---|---|---|
| Orchestration | Pipecat (OSS) | free |
| Telephony | Telnyx SIP | ~$0.002/min |
| Speech-to-text | faster-whisper (local) | free |
| Brain (LLM) | local model via Ollama/vLLM (OpenAI-compatible) | free |
| Voice cloning (TTS) | Chatterbox (local, RTX) | free |
| **All-in** | | **~$0.002–0.01/min** |

Managed fallback if the RTX isn't up yet: swap Chatterbox→Cartesia Sonic and
faster-whisper→Deepgram in `agent.py` (keys in `.env`); ~$0.04–0.06/min.

## Files

- `compliance.py` — the hard gate: consent + DNC + calling window + AI disclosure. Pure logic, unit-tested (`python compliance.py`).
- `prompts.py` — the seller-qualification + appointment-booking call brief.
- `clone_voice.py` — Chatterbox voice cloning from a short reference clip (RTX).
- `agent.py` — the Pipecat pipeline (STT→LLM→TTS). **Pin the imports** to the installed pipecat version (see the PIN block).
- `dial.py` — pulls consented leads, runs each through `compliance.can_call()`, places the call, logs the outcome. `--dry` shows who would be called and why.
- `.env.example` — copy to `.env` on the RTX box.
- consent capture lives in `../docs/home-value/andrew.html` (checkbox → `consent_to_ai_call`).
- DB columns: `../supabase/migration_014_voice_consent.sql` (applied).

## Run it

```bash
python voice-agent/compliance.py            # smoke-test the gate (works anywhere)
python voice-agent/dial.py --limit 20 --dry # see who is callable + why (safe, no calls)
python voice-agent/clone_voice.py "test" clone_test.wav   # test the cloned voice (needs RTX)
```

`--dry` is the only mode that runs until go-live is complete.

## Go-live checklist

1. RTX box online (IP/creds) with CUDA. Install `requirements.txt`, then
   `python -c "import pipecat"` and reconcile `agent.py`'s PIN block to the installed API.
2. Serve a local LLM (Ollama `ollama serve` or vLLM); set `OPENAI_BASE_URL`/`LLM_MODEL`.
3. Drop a 10–30s clean voice sample at `CLONE_REFERENCE_WAV`; verify `clone_voice.py`.
4. Telnyx: buy a number, register the caller ID, create a Voice API connection; set
   `TELNYX_API_KEY`/`TELNYX_FROM_NUMBER`/`TELNYX_CONNECTION_ID`.
5. Implement the Telnyx→Pipecat media bridge in `dial.place_call()` (the one TODO).
6. Confirm the funnel is capturing consent (submit a test opt-in with the box ticked;
   check `prospects.consent_to_ai_call`).
7. Run `dial.py --dry`, confirm the gate math, then drop `--dry`.

Nothing here dials a real number until steps 4–5 are done and `--dry` is removed.
