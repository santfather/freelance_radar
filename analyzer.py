"""Анализаторы заказов. Абстрактный BaseAnalyzer + реализации Ollama, DeepSeek, Gemini."""

import json
import os
import re
from abc import ABC, abstractmethod

import httpx

from models import Job, MAX_DESC_LENGTH

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
    @abstractmethod
    async def analyze(self, title: str, category: str, budget: str, description: str) -> dict:
        """Вернуть словарь с ключами: verdict, reason, complexity, estimated_hours."""
        ...

    def _build_prompt(self, title: str, category: str, budget: str, description: str) -> str:
        return USER_TEMPLATE.format(
            title=title, category=category,
            budget=budget or "not specified",
            description=description[:MAX_DESC_LENGTH] if description else "no description",
        )

    def _error_result(self, error_msg: str) -> dict:
        return {
            "verdict": "UNKNOWN",
            "reason": error_msg,
            "complexity": 0,
            "estimated_hours": 0,
        }

    async def _call_llm(self, url: str, payload: dict, headers: dict | None = None, timeout: int = 90) -> str:
        """Универсальный HTTP-вызов к LLM API.
        
        Возвращает сырой текст ответа. headers могут быть None (для Ollama без ключа).
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, json=payload, headers=headers or {}, timeout=timeout,
            )
            resp.raise_for_status()
            return resp.text


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

    def __init__(self, model: str | None = None, host: str | None = None):
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:14b")

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


async def check_ollama_available(model: str | None = None, host: str | None = None) -> tuple[bool, str]:
    """Проверить, доступна ли Ollama и нужная модель."""
    host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
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

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
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


async def check_deepseek_available(api_key: str | None = None) -> tuple[bool, str]:
    """Проверить, настроен ли DeepSeek API."""
    key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
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

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
                headers = {"X-Goog-Api-Key": self.api_key}
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                    json=payload,
                    headers=headers,
                    timeout=90,
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
            return _extract_result(raw)
        except Exception as e:
            return self._error_result(f"Gemini error: {e}")


async def check_gemini_available(api_key: str | None = None) -> tuple[bool, str]:
    """Проверить, настроен ли Gemini API."""
    key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not key:
        return False, "Gemini API key not set"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            headers = {"X-Goog-Api-Key": key}
            resp = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers=headers,
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


def get_analyzer(provider: str, **kwargs) -> BaseAnalyzer:
    """Фабрика — возвращает экземпляр анализатора по имени провайдера.

    Параметры:
        provider: имя провайдера (ollama/deepseek/gemini)
        **kwargs: передаются в конструктор анализатора (api_key, model, host)
    """
    provider = provider.lower()
    cls = PROVIDER_MAP.get(provider)
    if cls is None:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {', '.join(PROVIDER_MAP)}")
    return cls[0](**kwargs)
