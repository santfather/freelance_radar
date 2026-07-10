"""Ollama-based job analyzer. Supports both /api/chat and /api/generate endpoints."""

import json
import os
import re

import httpx

from models import Job, Verdict

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

SYSTEM_PROMPT = """You are a senior freelance developer evaluating job offers.
Your job: analyze a freelance order and decide if it's worth taking.

Criteria for TAKE:
- Clear requirements (you know what to build)
- Budget is realistic (not "do it for free" or suspiciously high)
- Technology stack you know (web, mobile, CMS, WordPress)
- Scope is manageable for 1 person in reasonable time

Criteria for SKIP:
- Vague or impossible requirements
- Budget too low for scope
- Requires large team or specialized knowledge you don't have
- Looks like spam or test

Respond ONLY with valid JSON, no markdown, no explanation outside JSON:
{
  "verdict": "TAKE" or "SKIP",
  "reason": "1-2 sentences explaining why",
  "complexity": 1-5,
  "estimated_hours": number
}"""

USER_TEMPLATE = """Job title: {title}
Category: {category}
Budget: {budget}
Description: {description}

Analyze this job offer."""


async def _call_generate(client: httpx.AsyncClient, full_prompt: str) -> str:
    """Use /api/generate (older Ollama versions)."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    resp = await client.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=90)
    resp.raise_for_status()
    return resp.json().get("response", "{}")


async def _call_chat(client: httpx.AsyncClient, prompt: str) -> str:
    """Use /api/chat (Ollama >= 0.1.14)."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    resp = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=90)
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "{}")


async def analyze_job(job: Job) -> Job:
    """Send job to Ollama and fill in verdict fields."""
    prompt = USER_TEMPLATE.format(
        title=job.title,
        category=job.category.value,
        budget=job.budget_raw or "not specified",
        description=job.description[:600] if job.description else "no description",
    )

    try:
        async with httpx.AsyncClient() as client:
            # Try /api/chat first, fall back to /api/generate
            try:
                raw = await _call_chat(client, prompt)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    print(f"[analyzer] /api/chat not found, using /api/generate")
                    full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
                    raw = await _call_generate(client, full_prompt)
                else:
                    raise

            result = _parse_response(raw)
            job.verdict = (
                Verdict(result["verdict"])
                if result.get("verdict") in ("TAKE", "SKIP")
                else Verdict.UNKNOWN
            )
            job.verdict_reason = result.get("reason", "")[:300]
            job.complexity = max(1, min(5, int(result.get("complexity") or 3)))
            job.estimated_hours = max(0, int(result.get("estimated_hours") or 0))
            job.analyzed = True

    except Exception as e:
        print(f"[analyzer] error on '{job.title[:40]}': {e}")
        job.verdict = Verdict.UNKNOWN
        job.verdict_reason = f"Analysis failed: {e}"
        job.analyzed = False

    return job


def _parse_response(raw: str) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return {}


async def check_ollama_available() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            model_base = OLLAMA_MODEL.split(":")[0]
            available = any(model_base in m for m in models)
            if not available:
                return False, f"Model '{OLLAMA_MODEL}' not found. Available: {', '.join(models) or 'none'}"
            return True, f"Ollama OK · {OLLAMA_MODEL}"
    except Exception as e:
        return False, f"Ollama not reachable: {e}"
