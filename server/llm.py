"""상위 LLM 클라이언트 — Anthropic Claude (공식 SDK).

.env 설정:
  ANTHROPIC_API_KEY  필수
  LLM_MODEL          기본 claude-opus-5 (비용 절감 시 claude-haiku-4-5 등)
  LLM_EFFORT         기본 low — 음성 대화라 지연 최소화. 품질 우선이면 high.
                     effort 미지원 모델(Haiku 4.5 등)에서는 자동으로 생략한다.
  LLM_AUX_MODEL      보조 호출(꼬리질문 재작성·영어 질문 번역) 모델. 기본 claude-haiku-4-5.
                     한 줄짜리 변환이라 작은 모델로 충분하고, 답변 모델이 Opus여도 이 호출이
                     빨라져 영어 질문·꼬리질문의 첫 소리가 약 1초 당겨진다 (11/8 Colab 측정:
                     번역 호출이 영어 질문 첫 글자를 Haiku 0.7→1.4초, Opus 1.6→2.9초로 늘림).
                     빈 값이면 LLM_MODEL과 같은 모델을 쓴다.
"""
from __future__ import annotations

import logging
import os

import anthropic

logger = logging.getLogger(__name__)

MODEL = os.environ.get("LLM_MODEL", "claude-opus-5")
EFFORT = os.environ.get("LLM_EFFORT", "low")
AUX_MODEL = os.environ.get("LLM_AUX_MODEL", "claude-haiku-4-5") or MODEL

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
    return _client


# effort 파라미터를 지원하지 않는 모델 — 보내면 400 에러가 난다
_NO_EFFORT_MODELS = ("claude-haiku-4-5", "claude-sonnet-4-5")


def _build_kwargs(system: str, user: str, max_tokens: int, model: str | None = None) -> dict:
    model = model or MODEL
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
    }
    if EFFORT and not model.startswith(_NO_EFFORT_MODELS):
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


def chat(system: str, user: str, max_tokens: int = 300, model: str | None = None) -> str:
    resp = _get_client().messages.create(**_build_kwargs(system, user, max_tokens, model))

    # 안전 분류기가 거부하면 content가 비어 있을 수 있으므로 먼저 확인
    _warn_if_truncated(resp.stop_reason, max_tokens)
    if resp.stop_reason == "refusal":
        return "죄송해요, 그 질문에는 답변드릴 수 없어요."

    return next(
        (block.text for block in resp.content if block.type == "text"), ""
    ).strip()


def aux_chat(system: str, user: str, max_tokens: int = 300) -> str:
    """보조 호출(재작성·번역)용 — AUX_MODEL로 보낸다. 답변 생성에는 chat/chat_stream을 쓴다."""
    return chat(system, user, max_tokens, model=AUX_MODEL)
