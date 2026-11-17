"""팔로업 재작성 우회 관문 (실험).

지금은 대화 기록이 한 줄이라도 있으면 매 턴 재작성 LLM 호출이 일어난다(측정 중앙값 0.89초).
이 모듈은 재작성이 필요 없는 질문만 골라 그 호출을 건너뛰게 한다.
원칙: 헷갈리면 항상 재작성한다. 건너뛰는 건 '확실히 독립적인 질문'일 때뿐이다.
틀려도 시간만 더 쓰지 답이 망가지지 않게 하려는 것이다.

관문 두 단계
  ① 꼬리질문 신호가 있으면 재작성 (검색하지 않고 바로 판단):
       - 영어 발화 (원문 검색 점수가 낮고 번역 호출이 따로 있어 이번 실험 대상이 아님)
       - 시작어 "그럼/그건/아니…", 지시어 "거기/방금/그거…", 형태 변경 요청 "영어로/짧게/다시…"
       - 아주 짧은 발화, 질문 단어뿐인 발화("신청 기간은 언제야?" — 무엇의 신청인지 대화에서 와야 함)
  ② 신호가 없으면 원래 발화로 먼저 검색해서(0.03초, 어차피 하는 일) 최고 점수가 기준(TAU) 이상이면
     독립 질문으로 보고 재작성을 생략한다. 기준 미만이면 재작성한다.

켜는 법: 환경변수 REWRITE_GATE=1. 요청 본문의 rewrite_gate 필드(true/false)가 있으면 그 값이 우선한다(전후 비교용).
기준 점수: 환경변수 REWRITE_GATE_TAU (기본 0.60). eval/rewrite_gate/run_eval.py로 정한다.
"""
from __future__ import annotations

import os
import re
from typing import Callable

DEFAULT_TAU = 0.60
SHORT_MAX = 7   # 공백·기호를 뺀 글자 수가 이 이하면 꼬리질문으로 본다

CUE_START = ("그럼", "그러면", "그리고", "그런데", "그래서", "그렇다면", "그건", "그거", "그게", "이건", "이거", "이게",
             "저건", "저거", "아니", "근데", "또 ", "그 ", "이 ", "저 ")
DEICTIC = ("그거", "그건", "그게", "이거", "이건", "이게", "저거", "저건", "거기", "여기", "아까", "방금", "앞에서",
           "위에서", "위의", "앞서", "그때", "그 경우", "그럼", "그러면")
FORMAT_CUES = ("영어로", "한국어로", "일본어로", "중국어로", "짧게", "간단히", "간단하게", "자세히", "자세하게",
               "다시 말", "다시 설명", "다시 한", "한 번 더", "한번 더", "쉽게", "천천히", "요약", "번역")
# 이 단어들뿐인 질문은 '무엇에 대한' 질문인지 대화에서 와야 한다
GENERIC = {"신청", "기간", "방법", "절차", "언제", "어떻게", "얼마", "얼마나", "몇", "뭐", "무엇", "어디", "어떤", "가능",
           "필요", "경우", "조건", "기준", "서류", "비용", "시간", "제한", "알려줘", "말해줘", "설명해줘", "알려", "대해",
           "그럼", "혹시", "좀", "더", "또"}
_PARTICLES = re.compile(r"(은|는|이|가|을|를|도|만|에|의|야|요|예요|이야|이에요|까지|부터|로|으로|해|돼|해야|있어|없어|할까|"
                        r"해요|돼요|인가|인지|나요|어요|지)+$")


def enabled(flag: bool | None = None) -> bool:
    """요청의 rewrite_gate 값이 있으면 그 값, 없으면 환경변수 REWRITE_GATE."""
    if flag is not None:
        return bool(flag)
    return os.getenv("REWRITE_GATE", "0").strip().lower() in ("1", "true", "yes", "on")


def tau() -> float:
    try:
        return float(os.getenv("REWRITE_GATE_TAU", DEFAULT_TAU))
    except ValueError:
        return DEFAULT_TAU


def _compact(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text)


def _generic_only(text: str) -> bool:
    tokens = [t for t in re.split(r"[\s,?!.]+", text.strip()) if t]
    if not tokens:
        return True
    for tok in tokens:
        stem = _PARTICLES.sub("", tok)
        if stem and len(stem) > 1 and stem not in GENERIC:
            return False
    return True


def followup_signal(utterance: str) -> str | None:
    """꼬리질문 신호가 있으면 그 이유를, 없으면 None을 돌려준다 (검색 없이 판단)."""
    u = utterance.strip()
    if not re.search(r"[가-힣]", u):
        return "영어 발화"
    if u.startswith(CUE_START):
        return "꼬리질문 시작어"
    if any(w in u for w in DEICTIC):
        return "지시어"
    if any(w in u for w in FORMAT_CUES):
        return "형태 변경 요청"
    if len(_compact(u)) <= SHORT_MAX:
        return "짧은 발화"
    if _generic_only(u):
        return "질문 단어뿐"
    return None


def decide(utterance: str, peek_score: Callable[[], float], threshold: float | None = None) -> tuple[bool, str]:
    """(재작성 호출 여부, 이유)를 돌려준다. peek_score는 신호가 없을 때만 불린다(원래 발화의 최고 검색 점수)."""
    signal = followup_signal(utterance)
    if signal:
        return True, signal
    th = tau() if threshold is None else threshold
    score = peek_score()
    if score >= th:
        return False, f"독립 질문 {score:.2f}"
    return True, f"검색 점수 {score:.2f}<{th:.2f}"
