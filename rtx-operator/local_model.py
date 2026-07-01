# -*- coding: utf-8 -*-
"""local_model.py - call the RTX's local LLM (Ollama, OpenAI-compatible endpoint).

This is the drop-in replacement for the cloud `ask_claude` the employee framework uses.
Point CLAUDE_CLI-style calls here so the operator reasons on the local model instead of
the paid cloud. Stdlib only (urllib) so it runs on a fresh RTX with no pip installs.

Env:
  OLLAMA_URL    default http://localhost:11434
  OLLAMA_MODEL  default qwen3-coder:30b   (already installed on the HK RTX 4070; see README)
  OLLAMA_NUM_CTX default 8192
"""
import os, json, urllib.request, urllib.error

URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-coder:30b")
NUMCTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))


def ask_local(prompt: str, system: str | None = None, model: str | None = None,
              temperature: float = 0.2, timeout: int = 300) -> str:
    """Send a chat completion to the local model and return the assistant text.
    Mirrors the shape of the framework's ask_claude(prompt, system) call."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({
        "model": model or MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": NUMCTX},
    }).encode()
    req = urllib.request.Request(f"{URL}/v1/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return f"[local-model HTTP {e.code}: {e.read()[:200].decode('utf-8','replace')}]"
    except Exception as e:
        return f"[local-model error: {e}]"


def health() -> tuple[bool, str]:
    """Is the local model server up and is the configured model pulled?"""
    try:
        with urllib.request.urlopen(f"{URL}/api/tags", timeout=10) as r:
            tags = json.loads(r.read())
        names = [m.get("name", "") for m in tags.get("models", [])]
        have = any(MODEL.split(":")[0] in n for n in names)
        return have, f"ollama up, model {'present' if have else 'MISSING - run: ollama pull ' + MODEL}"
    except Exception as e:
        return False, f"ollama not reachable at {URL}: {e}"


if __name__ == "__main__":
    ok, msg = health()
    print(msg)
    if ok:
        print("test:", ask_local("Reply with exactly the word: READY", temperature=0))
