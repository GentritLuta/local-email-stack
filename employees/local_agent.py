# -*- coding: utf-8 -*-
"""local_agent.py - agentic tool-calling loop against the RTX's local Ollama model.

Drop-in for _lib.ask_claude(system, prompt, cwd, timeout) used by employee.py when a
role's config sets "backend": "local". Unlike rtx-operator/local_model.py's ask_local()
(one-shot text completion, no tools), this drives a real tool-calling loop so a local
model can actually research: news, background facts, source pages, and images, plus
read-only access to the role's own data-inbox (mirrors Claude's allowed-tools boundary
of WebSearch/WebFetch/Read/Glob/Grep - research + read, never write/edit/bash/send).

Requires Ollama's OpenAI-compatible /v1/chat/completions endpoint with tool-calling
support (documented since Ollama 0.3+; qwen3-coder is a tool-calling-capable model per
its model card). NOT TESTED against the real RTX box as of 2026-07-02 - it is not
network-reachable yet (see memory rtx_machine_prep). Treat as built-and-syntax-checked,
not verified end-to-end, until the RTX connection is live.

Env (same names as rtx-operator/local_model.py, so one .env covers both):
  OLLAMA_URL      default http://localhost:11434
  OLLAMA_MODEL    default qwen3-coder:30b
  OLLAMA_NUM_CTX  default 8192
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import research_tools as RT

URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-coder:30b")
NUMCTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))

MAX_TOOL_ROUNDS = 12


def _scoped_file_tools(cwd: Path):
    """Read-only file tools scoped to cwd (the role's data-inbox / workspace), mirroring
    Claude's Read/Glob boundary. No writes, no paths outside cwd."""
    cwd = Path(cwd).resolve()

    def list_data_files() -> list:
        if not cwd.exists():
            return []
        return [str(p.relative_to(cwd)) for p in cwd.rglob("*") if p.is_file()]

    def read_data_file(filename: str, max_chars: int = 20000) -> dict:
        target = (cwd / filename).resolve()
        if cwd not in target.parents and target != cwd:
            return {"error": "path escapes the allowed folder"}
        if not target.exists() or not target.is_file():
            return {"error": f"no such file: {filename}"}
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": str(e)}
        return {"filename": filename, "text": text[:max_chars]}

    schemas = [
        {"type": "function", "function": {
            "name": "list_data_files",
            "description": "List files in your data drop folder.",
            "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {
            "name": "read_data_file",
            "description": "Read a file from your data drop folder.",
            "parameters": {"type": "object", "properties": {
                "filename": {"type": "string"}, "max_chars": {"type": "integer"}},
                "required": ["filename"]}}},
    ]
    funcs = {"list_data_files": list_data_files, "read_data_file": read_data_file}
    return schemas, funcs


def _chat(messages: list, tools: list, timeout: int) -> dict:
    body = json.dumps({
        "model": MODEL, "messages": messages, "stream": False,
        "tools": tools if tools else None,
        "options": {"temperature": 0.3, "num_ctx": NUMCTX},
    }).encode()
    req = urllib.request.Request(f"{URL}/v1/chat/completions", data=body, method="POST",
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def health() -> tuple:
    try:
        with urllib.request.urlopen(f"{URL}/api/tags", timeout=10) as r:
            tags = json.loads(r.read())
        names = [m.get("name", "") for m in tags.get("models", [])]
        have = any(MODEL.split(":")[0] in n for n in names)
        return have, f"ollama up, model {'present' if have else 'MISSING - run: ollama pull ' + MODEL}"
    except Exception as e:
        return False, f"ollama not reachable at {URL}: {e}"


def ask_local_agent(system: str, prompt: str, cwd: Path, timeout: int = 900) -> str:
    """Mirrors _lib.ask_claude's signature and contract (raises RuntimeError on hard
    failure, otherwise returns the model's final raw text including the EMPLOYEE_META
    block employee.py's _parse_meta expects)."""
    file_schemas, file_funcs = _scoped_file_tools(cwd)
    tools = RT.TOOL_SCHEMAS + file_schemas
    funcs = {**RT.TOOL_FUNCS, **file_funcs}

    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    per_call_timeout = max(60, timeout // MAX_TOOL_ROUNDS)

    for round_i in range(MAX_TOOL_ROUNDS):
        try:
            data = _chat(messages, tools, per_call_timeout)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"local model HTTP {e.code}: {e.read()[:300].decode('utf-8','replace')}")
        except Exception as e:
            raise RuntimeError(f"local model unreachable: {e}")

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            content = (msg.get("content") or "").strip()
            if content:
                return content
            break  # empty content, no tool calls - fall through to forced-final below

        messages.append(msg)
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            func = funcs.get(name)
            if func is None:
                result = {"error": f"unknown tool: {name}"}
            else:
                try:
                    result = func(**args)
                except Exception as e:
                    result = {"error": str(e)}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", name),
                "content": json.dumps(result, ensure_ascii=False)[:8000],
            })

    # Ran out of tool rounds (or got an empty turn) - force a final, tool-free answer.
    messages.append({"role": "user", "content":
                     "Stop researching now. Write your complete final work product and "
                     "the metadata block, using only what you have found so far."})
    try:
        data = _chat(messages, tools=None, timeout=per_call_timeout)
    except Exception as e:
        raise RuntimeError(f"local model unreachable on forced-final call: {e}")
    content = ((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("local model returned nothing after forced-final call")
    return content


if __name__ == "__main__":
    ok, msg = health()
    print(msg)
