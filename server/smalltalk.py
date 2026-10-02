"""인사·잡담 감지 — 학칙 검색과 게이트를 건너뛸 발화를 고른다.

"안녕", "고마워" 같은 말까지 검색에 넣으면 관련 조항이 없어 게이트가 보류 멘트로
막아버린다. 짧고, 인사·잡담 패턴에 맞고, 학사 키워드가 없는 발화만 잡담으로 본다
("안녕, 휴학 어떻게 해?"처럼 질문이 섞인 발화는 정상 경로로 보낸다).
"""
from __future__ import annotations

import re

MAX_LEN = 20

_SMALLTALK = re.compile(
    r"안녕|반가|고마|감사|수고|잘\s?가|잘\s?있|좋은\s?(아침|하루|밤)|하이|헬로|"
    r"누구(야|니|세요|에요)|이름이?\s?뭐|자기\s?소개|뭐\s?할\s?수\s?있|"
    r"\b(hi|hello|hey|thanks|thank you|bye|good (morning|night)|who are you|what can you do)\b",
    re.IGNORECASE,
)

_DOMAIN = re.compile(
    r"휴학|복학|수강|장학|졸업|등록|신청|학점|성적|기숙사|비자|증명서|도서관|학칙|"
    r"전공|재학|입학|외국인|유학생|"
    r"\b(leave|enroll|course|credit|scholarship|graduat|visa|tuition|dorm)",
    re.IGNORECASE,
)


def is_smalltalk(utterance: str) -> bool:
    text = utterance.strip()
    return (
        len(text) <= MAX_LEN
        and bool(_SMALLTALK.search(text))
        and not _DOMAIN.search(text)
    )


# 시스템 프롬프트는 그대로 두고, 이번 턴 사용자 메시지 끝에 붙이는 안내
NOTE = {
    "ko": "(이번 발화는 인사나 잡담이다. 규정 안내가 필요 없으니 치토답게 한두 문장으로 "
          "짧게 응대하고, 학사·행정·캠퍼스에 대해 물어보도록 자연스럽게 권하라.)",
    "en": "(This turn is a greeting or small talk. No regulation lookup is needed — reply "
          "in character as Chito in one or two short sentences and invite questions about "
          "academics, administration, or campus.)",
}
