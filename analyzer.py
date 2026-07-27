"""Анализаторы заказов. Абстрактный BaseAnalyzer + реализации Ollama, DeepSeek, Gemini."""

import json
import os
import re
from abc import ABC, abstractmethod

import httpx

from models import Job

# ── Промпты (общие для всех анализаторов) ────────────────────────────────────

SYSTEM_PROMPT = """You are a senior freelance developer evaluating job offers.
Your job: analyze a freelance order and decide if it's worth taking.

Criteria for TAKE:
- Clear requirements (you know what to build)
- Budget is realistic (not "do it for free" or suspiciously high)
- Technology stack you know (web, mobile, CMS: WordPress, Drupal, MODX, Bitrix)
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


# ── Базовый класс ────────────────────────────────────────────────────────────

class BaseAnalyzer(ABC):
    """Абстрактный анализатор заказов."""

    @abstractmethod
    async def analyze(self, title: str, category: str, budget: str, description: str) -> dict:
        """Вернуть словарь с ключами: verdict, reason, complexity, estimated_hours."""
        ...

    def _build_prompt(self, title: str, category: str, budget: str, description: str) -> str:
        return USER_TEMPLATE.format(
            title=title, category=category,
            budget=budget or "not specified",
            description=description[:600] if description else "no description",
        )

    def _error_result(self, error_msg: str) -> dict:
        return {
            "verdict": "UNKNOWN",
            "reason": error_msg,
            "complexity": 0,
            "estimated_hours": 0,
        }


# ── Вспомогательная функция парсинга ответа ──────────────────────────────────

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


def _extract_result(raw: str) -> dict:
    """Распарсить ответ LLM и нормализовать сложность/часы."""
    result = _parse_response(raw)
    return {
        "verdict": result.get("verdict", "UNKNOWN"),
        "reason": (result.get("reason") or "")[:300],
        "complexity": max(1, min(5, int(result.get("complexity") or 3))),
        "estimated_hours": max(0, int(result.get("estimated_hours") or 0)),
    }


# ── OllamaAnalyzer ───────────────────────────────────────────────────────────

class OllamaAnalyzer(BaseAnalyzer):
    """Анализ через локальную Ollama (поддерживает /api/chat и /api/generate)."""

    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "mistral")

    async def analyze(self, title: str, category: str, budget: str, description: str) -> dict:
        prompt = self._build_prompt(title, category, budget, description)
        try:
            async with httpx.AsyncClient() as client:
                try:
                    raw = await self._call_chat(client, prompt)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
                        raw = await self._call_generate(client, full_prompt)
                    else:
                        raise
            return _extract_result(raw)
        except Exception as e:
            return self._error_result(f"Ollama error: {e}")

    async def _call_chat(self, client: httpx.AsyncClient, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
        resp = await client.post(f"{self.host}/api/chat", json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "{}")

    async def _call_generate(self, client: httpx.AsyncClient, full_prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
        resp = await client.post(f"{self.host}/api/generate", json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json().get("response", "{}")


async def check_ollama_available() -> tuple[bool, str]:
    """Проверить, доступна ли Ollama и нужная модель."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "mistral")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{host}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            model_base = model.split(":")[0]
            available = any(model_base in m for m in models)
            if not available:
                return False, f"Model '{model}' not found. Available: {', '.join(models) or 'none'}"
            return True, f"Ollama OK · {model}"
    except Exception as e:
        return False, f"Ollama not reachable: {e}"


# ── DeepSeekAnalyzer ─────────────────────────────────────────────────────────

class DeepSeekAnalyzer(BaseAnalyzer):
    """Анализ через DeepSeek API (OpenAI-совместимый)."""

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.base_url = "https://api.deepseek.com/v1"

    async def analyze(self, title: str, category: str, budget: str, description: str) -> dict:
        prompt = self._build_prompt(title, category, budget, description)
        if not self.api_key:
            return self._error_result("DeepSeek API key not configured")
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 512,
                }
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=90,
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
            return _extract_result(raw)
        except Exception as e:
            return self._error_result(f"DeepSeek error: {e}")


async def check_deepseek_available() -> tuple[bool, str]:
    """Проверить, настроен ли DeepSeek API."""
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        return False, "DeepSeek API key not set"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.deepseek.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            return True, "DeepSeek API OK"
    except Exception as e:
        return False, f"DeepSeek API error: {e}"


# ── GeminiAnalyzer ───────────────────────────────────────────────────────────

class GeminiAnalyzer(BaseAnalyzer):
    """Анализ через Google Gemini API."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    async def analyze(self, title: str, category: str, budget: str, description: str) -> dict:
        prompt = self._build_prompt(title, category, budget, description)
        if not self.api_key:
            return self._error_result("Gemini API key not configured")
        try:
            full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
            async with httpx.AsyncClient() as client:
                payload = {
                    "contents": [{
                        "parts": [{"text": full_prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 512,
                    },
                }
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
                    f"?key={self.api_key}",
                    json=payload,
                    timeout=90,
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
            return _extract_result(raw)
        except Exception as e:
            return self._error_result(f"Gemini error: {e}")


async def check_gemini_available() -> tuple[bool, str]:
    """Проверить, настроен ли Gemini API."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return False, "Gemini API key not set"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            )
            resp.raise_for_status()
            return True, "Gemini API OK"
    except Exception as e:
        return False, f"Gemini API error: {e}"


# ── Фабрика анализаторов ─────────────────────────────────────────────────────

PROVIDER_MAP = {
    "ollama": (OllamaAnalyzer, check_ollama_available),
    "deepseek": (DeepSeekAnalyzer, check_deepseek_available),
    "gemini": (GeminiAnalyzer, check_gemini_available),
}

PROVIDER_NAMES = {
    "ollama": "Ollama (локально)",
    "deepseek": "DeepSeek API",
    "gemini": "Gemini API",
}


def get_analyzer(provider: str) -> BaseAnalyzer:
    """Фабрика — возвращает экземпляр анализатора по имени провайдера."""
    provider = provider.lower()
    cls = PROVIDER_MAP.get(provider)
    if cls is None:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {', '.join(PROVIDER_MAP)}")
    return cls[0]()


async def check_provider_available(provider: str) -> tuple[bool, str]:
    """Проверить доступность провайдера."""
    provider = provider.lower()
    entry = PROVIDER_MAP.get(provider)
    if entry is None:
        return False, f"Unknown provider '{provider}'"
    return await entry[1]()
