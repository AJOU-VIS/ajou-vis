"""팔로업 질문 재작성 (프롬프트 계약 ④) — RAG 검색 전에 호출.

"그럼 휴학은?" → 독립 질문으로 재작성. 형태 변경 요청("영어로", "짧게")은
[NO_SEARCH]를 반환해 검색을 건너뛴다. 첫 턴(히스토리 없음)은 LLM 호출 없이
원문을 그대로 쓴다(지연 절약).
"""
from __future__ import annotations

import prompts_loader

NO_SEARCH = "[NO_SEARCH]"


def rewrite(history: str, utterance: str, llm_chat) -> tuple[str, bool]:
    """(검색용 질문, 검색 필요 여부)를 반환한다."""
    if not history.strip():
        return utterance, True
    prompt = prompts_loader.rewrite_prompt(history, utterance)
    # rewrite.md는 [지시]/[입력] 구조라 통째로 사용자 메시지로 보낸다
    result = llm_chat(system="", user=prompt, max_tokens=100)
    line = result.strip().splitlines()[0].strip() if result.strip() else utterance
    if NO_SEARCH in line:
        return utterance, False
    return line or utterance, True


_TRANSLATE = (
    "다음 질문을 아주대학교 학칙·학사 규정을 검색하기 좋은 자연스러운 한국어 질문 한 문장으로 "
    "옮겨라. 학사 용어는 학칙에서 쓰는 한국어 용어로 바꾼다. "
    "번역된 질문 한 줄만 출력하고 설명·따옴표를 붙이지 않는다.\n\n"
    "질문: {question}"
)


def search_query(question: str, lang: str, llm_chat) -> str:
    """검색에 쓸 질문. 코퍼스(학칙)가 한국어라 영어 질문은 한국어로 옮겨 검색한다.

    영어 질문을 그대로 검색하면 관련 조항이어도 유사도가 0.52~0.57로 낮게 나와
    게이트 임계값(0.5)과 여유가 거의 없다. 답변 생성에는 원래 질문을 그대로 쓴다.
    """
    if lang != "en":
        return question
    result = llm_chat(system="", user=_TRANSLATE.format(question=question), max_tokens=100)
    line = result.strip().splitlines()[0].strip() if result.strip() else ""
    # 번역 결과에 한글이 없으면(실패) 원문으로 검색
    return line if any("가" <= ch <= "힣" for ch in line) else question
