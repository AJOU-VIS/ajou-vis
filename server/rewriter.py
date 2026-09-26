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
    result = llm_chat(system="", user=prompt, max_tokens=100, temperature=0.0)
    line = result.strip().splitlines()[0].strip() if result.strip() else utterance
    if NO_SEARCH in line:
        return utterance, False
    return line or utterance, True
