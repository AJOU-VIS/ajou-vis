"""팔로업 질문 재작성 (프롬프트 계약 ④) — RAG 검색 전에 호출.

"그럼 휴학은?" → 독립 질문으로 재작성. 형태 변경 요청("영어로", "짧게")은
[NO_SEARCH]를 반환해 검색을 건너뛴다. 첫 턴(히스토리 없음)은 LLM 호출 없이
원문을 그대로 쓴다(지연 절약).

[SEATS] 추가: 도서관 좌석처럼 실시간으로 바뀌는 정보는 벡터DB 검색이 아니라
realtime.py의 API 직접 호출로 처리해야 하므로, 어떤 소스를 쓸지(source)도
함께 반환하도록 확장했다. 좌석 키워드는 LLM 호출 전에 먼저 걸러서 지연을
아낀다 (규정 재작성용 LLM 호출 자체가 필요 없는 케이스이기도 함).
"""
from __future__ import annotations

import prompts_loader

NO_SEARCH = "[NO_SEARCH]"

# 좌석 질문으로 바로 판별할 키워드. 넓게 잡기보다, 오탐(다른 질문을 좌석으로
# 잘못 분류)을 줄이는 쪽으로 보수적으로 시작 — 필요하면 더 추가.
SEAT_KEYWORDS = ("좌석", "열람실", "자리 있", "빈자리", "자리 남")


def _is_seat_question(utterance: str) -> bool:
    return any(kw in utterance for kw in SEAT_KEYWORDS)


def rewrite(history: str, utterance: str, llm_chat) -> tuple[str, bool, str]:
    """(검색/조회용 질문, 검색 필요 여부, 소스 태그)를 반환한다.
    소스 태그는 "chroma"(규정·행사·시설 벡터 검색) | "seats"(실시간 좌석
    API 직접 호출) | "none"(검색 불필요, 형태 변경 등) 중 하나.
    """
    if _is_seat_question(utterance):
        return utterance, True, "seats"

    if not history.strip():
        return utterance, True, "chroma"

    prompt = prompts_loader.rewrite_prompt(history, utterance)
    # rewrite.md는 [지시]/[입력] 구조라 통째로 사용자 메시지로 보낸다
    result = llm_chat(system="", user=prompt, max_tokens=100)
    line = result.strip().splitlines()[0].strip() if result.strip() else utterance

    if NO_SEARCH in line:
        return utterance, False, "none"
    return line or utterance, True, "chroma"
