"""신뢰도 게이트 (프롬프트 계약 ①): 근거가 없으면 LLM을 호출하지 않는다.

검색결과가 비었거나 최고 점수가 임계값 미만이면 정형 보류 응답을 반환해
무근거 회피를 프롬프트 준수 여부와 무관하게 보장한다. 게이트를 통과한
회색지대(근거 애매·조건 상이)만 LLM이 판단한다.
"""
from __future__ import annotations

import os

from rag import SearchHit

SCORE_THRESHOLD = float(os.environ.get("GATE_SCORE_THRESHOLD", "0.5"))

# 페르소나의 보류 멘트 (prompts/persona_ko.md · persona_en.md 응답 톤 샘플)
DEFERRAL = {
    "ko": "음, 그건 제가 가진 자료로는 확실하지 않아요. 정확한 건 학사지원팀에 확인해보는 게 좋아요!",
    "en": "Hmm, I can't confirm that from what I have. It's best to check with the Academic Support Team.",
}


def passes(hits: list[SearchHit]) -> bool:
    return bool(hits) and max(h.score for h in hits) >= SCORE_THRESHOLD


def deferral_message(lang: str) -> str:
    return DEFERRAL.get(lang, DEFERRAL["en"])
