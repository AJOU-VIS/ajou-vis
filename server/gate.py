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
# 게이트에서 막히면 질문 영역을 모르므로 부서 이름 대신 포탈·홈페이지로 안내한다 (시스템 프롬프트 v2 —
# 전에 쓰던 '학사지원팀'은 검색 자료에 없는 이름). 영어 문장 앞 "Hmm,"은 페르소나 v2에서 뺀 감탄사.
# 보류 멘트는 마침표로 끝낸다 (페르소나 v2.3: 느낌표는 인사할 때만).
DEFERRAL = {
    "ko": "그건 제가 가진 자료로는 확실하지 않아요. 정확한 건 학사서비스 포탈이나 학교 홈페이지에서 확인해보는 게 좋아요.",
    "en": "I can't confirm that from what I have. It's best to check the academic services portal or the university website.",
}


def passes(hits: list[SearchHit]) -> bool:
    return bool(hits) and max(h.score for h in hits) >= SCORE_THRESHOLD


def deferral_message(lang: str) -> str:
    return DEFERRAL.get(lang, DEFERRAL["en"])
