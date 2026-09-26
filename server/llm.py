"""상위 LLM 클라이언트 — OpenAI 호환 API라면 무엇이든 (.env로 교체 가능)."""
from __future__ import annotations

import os

import httpx

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT_S", "30"))


def chat(system: str, user: str, max_tokens: int = 300, temperature: float = 0.3) -> str:
    resp = httpx.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
