"""상위 LLM 클라이언트 — Anthropic Claude (공식 SDK).

.env 설정:
  ANTHROPIC_API_KEY  필수
  LLM_MODEL          기본 claude-opus-5 (비용 절감 시 claude-haiku-4-5 등)
  LLM_EFFORT         기본 low — 음성 대화라 지연 최소화. 품질 우선이면 high.
"""
from __future__ import annotations

import os

import anthropic

MODEL = os.environ.get("LLM_MODEL", "claude-opus-5")
EFFORT = os.environ.get("LLM_EFFORT", "low")

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
    return _client


def chat(system: str, user: str, max_tokens: int = 300) -> str:
    kwargs: dict = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "output_config": {"effort": EFFORT},
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        kwargs["system"] = system

    resp = _get_client().messages.create(**kwargs)

    # 안전 분류기가 거부하면 content가 비어 있을 수 있으므로 먼저 확인
    if resp.stop_reason == "refusal":
        return "죄송해요, 그 질문에는 답변드릴 수 없어요."

    return next(
        (block.text for block in resp.content if block.type == "text"), ""
    ).strip()
