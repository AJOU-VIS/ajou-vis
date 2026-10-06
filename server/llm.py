"""상위 LLM 클라이언트 — Anthropic Claude (공식 SDK).

.env 설정:
  ANTHROPIC_API_KEY  필수
  LLM_MODEL          기본 claude-opus-5 (비용 절감 시 claude-haiku-4-5 등)
  LLM_EFFORT         기본 low — 음성 대화라 지연 최소화. 품질 우선이면 high.
                     effort 미지원 모델(Haiku 4.5 등)에서는 자동으로 생략한다.
"""
from __future__ import annotations

import logging
import os

import anthropic

logger = logging.getLogger(__name__)

MODEL = os.environ.get("LLM_MODEL", "claude-opus-5")
EFFORT = os.environ.get("LLM_EFFORT", "low")

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
    return _client


# effort 파라미터를 지원하지 않는 모델 — 보내면 400 에러가 난다
_NO_EFFORT_MODELS = ("claude-haiku-4-5", "claude-sonnet-4-5")


def _build_kwargs(system: str, user: str, max_tokens: int) -> dict:
    kwargs: dict = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
    }
    if EFFORT and not MODEL.startswith(_NO_EFFORT_MODELS):
        kwargs["output_config"] = {"effort": EFFORT}
    if system:
        kwargs["system"] = system
    return kwargs


def chat_stream(system: str, user: str, max_tokens: int = 300):
    """답변 텍스트를 토큰 단위로 yield — 음성 파이프라인이 첫 문장부터 TTS를 시작할 수 있게."""
    with _get_client().messages.stream(**_build_kwargs(system, user, max_tokens)) as stream:
        for text in stream.text_stream:
            yield text
        _warn_if_truncated(stream.get_final_message().stop_reason, max_tokens)


def _warn_if_truncated(stop_reason: str | None, max_tokens: int) -> None:
    """출력 상한에 걸려 답변이 문장 중간에서 잘리면 경고를 남긴다 (음성으로는 어색하게 끊김)."""
    if stop_reason == "max_tokens":
        logger.warning("LLM 답변이 출력 상한(%d토큰)에서 잘림 — 프롬프트 길이 규칙 또는 max_tokens 확인", max_tokens)


def chat(system: str, user: str, max_tokens: int = 300) -> str:
    resp = _get_client().messages.create(**_build_kwargs(system, user, max_tokens))

    # 안전 분류기가 거부하면 content가 비어 있을 수 있으므로 먼저 확인
    _warn_if_truncated(resp.stop_reason, max_tokens)
    if resp.stop_reason == "refusal":
        return "죄송해요, 그 질문에는 답변드릴 수 없어요."

    return next(
        (block.text for block in resp.content if block.type == "text"), ""
    ).strip()
