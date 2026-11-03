"""위기 발화 감지 — 검색·게이트보다 먼저 보고, 맞으면 정해진 상담 안내로 바로 답한다.

"죽고 싶어" 같은 말은 학칙 검색 점수가 낮아 게이트가 "포탈에서 확인해보는 게 좋아요"
보류 멘트로 막아 버렸다 (11/3 스모크 X12 dry-run). 말이 매번 달라지면 안 되는 안내라
LLM에 맡기지 않고 고정 문장을 쓴다. 상담소 번호는 검색 자료(학생 상담 안내·유학생 상담
안내)에 있는 것이고, 109(보건복지부 자살예방상담전화, 24시간·무료)와 119는 자료 밖 공공 번호다.
"""
from __future__ import annotations

import re

_CRISIS = re.compile(
    r"죽고\s?싶|죽어\s?버리|자살|목숨을?\s?끊|살기\s?싫|살고\s?싶지\s?않|사라지고\s?싶|자해|극단적\s?선택|"
    r"\b(kill myself|suicid\w*|want to die|end my life|self[- ]?harm|hurt myself|don'?t want to live)\b",
    re.IGNORECASE,
)

# 음성으로 읽히므로 괄호 없이, 페르소나 말투(해요체·'-시-' 없음)로
MESSAGE = {
    "ko": "많이 힘들었겠어요, 말해 줘서 고마워요. 혼자 견디지 말고 학생상담소 031-219-2191에 꼭 이야기해 보세요. "
          "지금 위험하다고 느껴지면 자살예방상담전화 109나 119에 바로 전화해 주세요.",
    "en": "I'm really sorry you're going through this, and thank you for telling me. Please reach out to the "
          "international student counselor at 031-219-3598, who counsels in English, or the Student Counseling "
          "Center at 031-219-2191. If you feel you might be in danger right now, call 109 or 119 right away.",
}


def is_crisis(utterance: str) -> bool:
    return bool(_CRISIS.search(utterance))


def message(lang: str) -> str:
    return MESSAGE.get(lang, MESSAGE["en"])
