"""persona_engine.py — innovation #5.

Renders Qwen 32B prompts injected with the active sender persona's voice profile.
n8n calls /render to get back {system_message, user_message, signature}.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="persona-engine", version="1.0.0")

PERSONAS_PATH = Path(os.environ.get("PERSONAS_PATH", "/app/personas.yaml"))
_personas: dict = yaml.safe_load(PERSONAS_PATH.read_text(encoding="utf-8"))


class RenderRequest(BaseModel):
    persona: str       # "m1" .. "m10"
    task: str          # "cold_initial" | "cold_followup" | "warmup_send" | "warmup_reply" | "personalization"
    context: dict      # {company_name, owner_name, website, scraped_site_text, ...}


class RenderResponse(BaseModel):
    system_message: str
    user_message: str
    signature: str


def persona_block(p: dict) -> str:
    quirks = ", ".join(p["voice"].get("quirks", []))
    avoid = ", ".join(p["voice"].get("avoid", []))
    return (
        f"You are {p['name']}, {p['role']}. "
        f"{p['company_one_liner']}\n\n"
        f"VOICE: {p['voice']['register']}. "
        f"Quirks to use: {quirks}. "
        f"NEVER do: {avoid}.\n"
        f"You always send from {p['signature'].splitlines()[-1].strip()}.\n"
    )


SYSTEM_TEMPLATES = {
    "cold_initial": (
        "{persona_block}\n"
        "TASK: Write a short cold email (2 short paragraphs max + sign-off) to a small-business owner. "
        "Reference one specific thing from the supplied site text — never invent. "
        "End with one specific question, not a generic CTA. "
        "Subject line first, then a blank line, then the body. "
        "Do not include the signature — it gets appended automatically."
    ),
    "cold_followup": (
        "{persona_block}\n"
        "TASK: Write a short follow-up email (1 paragraph + sign-off) to someone who didn't reply to the previous message. "
        "Add a small new piece of value, not 'just bumping this'. "
        "Reference the original observation. No subject line — this is a thread reply."
    ),
    "warmup_send": (
        "{persona_block}\n"
        "TASK: Write a casual email to a colleague (also a founder/operator). 30–80 words. "
        "Realistic subject. Tone matches your VOICE. Vary the topic between: a recent observation, "
        "a question, a quick win to share, a meeting suggestion. NO links in the first 14 days of warmup. "
        "Subject line first, then a blank line, then the body."
    ),
    "warmup_reply": (
        "{persona_block}\n"
        "TASK: Write a 1–3 sentence reply to a casual work email from a colleague. "
        "Sometimes short ('makes sense, yeah'). Sometimes ask a follow-up question. "
        "Tone matches your VOICE. NO links. Plain text only."
    ),
    "personalization": (
        "{persona_block}\n"
        "TASK: Write a 2–3 sentence opening line for a cold email. "
        "Reference one specific thing from the supplied site text. "
        "Don't pitch, don't sell, just demonstrate genuine attention. "
        "Output the opening text only, nothing else."
    ),
}


def render_user_message(task: str, ctx: dict) -> str:
    if task == "personalization":
        return (
            f"Company: {ctx.get('company_name','')}\n"
            f"Owner: {ctx.get('owner_name','')}\n"
            f"Website: {ctx.get('website','')}\n\n"
            f"SITE TEXT (excerpt):\n{ctx.get('scraped_site_text','')[:3000]}"
        )
    if task in ("cold_initial", "cold_followup"):
        return (
            f"Recipient: {ctx.get('owner_name','')} at {ctx.get('company_name','')}\n"
            f"Website: {ctx.get('website','')}\n\n"
            f"OPENING LINE (use this verbatim as the first sentence):\n{ctx.get('personalization','')}\n\n"
            f"SITE TEXT (for context, do not quote):\n{ctx.get('scraped_site_text','')[:2000]}"
        )
    if task in ("warmup_send", "warmup_reply"):
        return (
            f"Counterparty: {ctx.get('peer_persona_name','')} at {ctx.get('peer_domain','')}\n"
            f"Their last message (if reply):\n{ctx.get('last_message','')}"
        )
    return ""


@app.post("/render", response_model=RenderResponse)
async def render(req: RenderRequest) -> RenderResponse:
    p = _personas.get(req.persona)
    if not p:
        raise HTTPException(404, f"unknown persona {req.persona}")
    template = SYSTEM_TEMPLATES.get(req.task)
    if not template:
        raise HTTPException(400, f"unknown task {req.task}")
    system = template.format(persona_block=persona_block(p))
    user = render_user_message(req.task, req.context)
    return RenderResponse(system_message=system, user_message=user, signature=p["signature"])


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
