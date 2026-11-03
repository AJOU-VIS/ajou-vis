"""턴 기록 — 웹 화면이 출처 카드·연락처·치토 표정을 그릴 때 쓰는 읽기 전용 정보 (11/3).

실시간 음성 연결(realtime)로는 답 글자와 소리만 화면에 간다. 그 턴에 검색된 조각과 처리 경로는
여기에 잠깐 기억해 두었다가 GET /v1/turns/latest 로 내준다. LLM 답·시스템 프롬프트·페르소나는
바꾸지 않는다 — 화면용 정보는 이미 검색된 자료와 서버 경로에서만 만든다.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque

from rag import SearchHit

MAX_TURNS = 50
_turns: deque[dict] = deque(maxlen=MAX_TURNS)
_lock = threading.Lock()
_seq = 0

# 치토 표정 분류 — 스모크 점검이 보류 답을 가르는 문구와 같은 계열
_NOSCOPE = re.compile(
    r"대신 해\s?(드릴|줄) 수 없|조회해\s?드릴 수 없|처리해\s?드릴 수 없|"
    r"can't (look up|do that for you|check)|cannot look up",
    re.I,
)
_DEFER = re.compile(
    r"확실하지 않|확인되지 않|확인이 어려|확인할 수 없|알 수 없|자료에는?[^.!?]*없|"
    r"can't confirm|can't tell|don't have|isn't in what I have",
    re.I,
)

# 담당 부서 연락처 — 검색 자료에 있는 번호만 (문서명·주소는 출처 표시용).
# 답에 이 부서 이름이 나오면 화면이 연락처 줄로 보여 준다. LLM 답에는 넣지 않는다.
CONTACTS = [
    {"dept": "교무팀", "aliases": ["교무팀", "Academic Affairs Team"], "label": "등록·학적 문의",
     "phone": "031-219-2012, 2014", "source": "아주대학교 등록금 안내", "url": "https://www.ajou.ac.kr/kr/bachelor/tuition.do"},
    {"dept": "재무회계팀", "aliases": ["재무회계팀", "Finance and Accounting Team"], "label": "등록금 수납·고지서",
     "phone": "031-219-2079", "source": "아주대학교 등록금 안내", "url": "https://www.ajou.ac.kr/kr/bachelor/tuition.do"},
    {"dept": "학생지원팀", "aliases": ["학생지원팀", "Student Support Team"], "label": "장학금",
     "phone": "031-219-2038, 2035, 2039", "source": "아주대학교 교내장학 안내", "url": "https://www.ajou.ac.kr/kr/bachelor/scholarship-school01.do"},
    {"dept": "국제협력처 유학생입학팀", "aliases": ["유학생입학팀", "International Admission Office"], "label": "외국인 유학생",
     "phone": "031-219-3520 · admission@ajou.ac.kr", "source": "아주대학교 유학생 연락처 안내", "url": "https://www.ajou.ac.kr/iadmissions/undergraduate/contact.do"},
    {"dept": "학생상담소", "aliases": ["학생상담소", "Student Counseling Center"], "label": "학생 상담",
     "phone": "031-219-2191", "source": "아주대학교 학생상담 안내", "url": "https://www.ajou.ac.kr/kr/life/consulting.do"},
]
_COLLEGE_OFFICE = re.compile(r"교학팀|academic affairs office", re.I)


def classify(path: str, answer: str) -> str:
    """치토 표정: crisis · smalltalk · sorry(보류) · noscope(범위 밖) · answer."""
    if path in ("crisis", "smalltalk"):
        return path
    if path == "gate_block":
        return "sorry"
    if _NOSCOPE.search(answer):
        return "noscope"
    if _DEFER.search(answer):
        return "sorry"
    return "answer"


def _norm(text: str) -> str:
    return re.sub(r"[\s/·]", "", text.replace("아주대학교", ""))


def sources_of(hits: list[SearchHit], answer: str) -> list[dict]:
    """검색 조각을 문서별로 묶는다. 답에 이름이 나온 문서를 앞에 둔다 (cited=True)."""
    groups: dict[tuple[str, str], dict] = {}
    for h in hits:
        key = (h.source_name, h.url)
        g = groups.setdefault(key, {"doc": h.source_name, "url": h.url, "articles": [], "excerpt": h.text[:600],
                                    "score": round(h.score, 3)})
        if h.article and h.article not in g["articles"]:
            g["articles"].append(h.article)
    flat_answer = _norm(answer)
    out = list(groups.values())
    for g in out:
        g["cited"] = bool(_norm(g["doc"])) and _norm(g["doc"]) in flat_answer
    return sorted(out, key=lambda g: not g["cited"])


def contacts_of(answer: str) -> list[dict]:
    found = [
        {k: c[k] for k in ("dept", "label", "phone", "source", "url")}
        for c in CONTACTS if any(a.lower() in answer.lower() for a in c["aliases"])
    ]
    if _COLLEGE_OFFICE.search(answer):
        found.append({"dept": "소속 학과 교학팀", "label": "학과별 번호는 각 안내 페이지의 문의사항", "phone": "",
                      "source": "", "url": ""})
    return found


def record(*, lang: str, question: str, answer: str, path: str, hits: list[SearchHit] | None = None) -> dict:
    global _seq
    hits = hits or []
    with _lock:
        _seq += 1
        turn = {
            "seq": _seq,
            "ts": time.time(),
            "lang": lang,
            "question": question,
            "answer": answer,
            "path": path,
            "kind": classify(path, answer),
            "sources": sources_of(hits, answer) if path not in ("crisis", "smalltalk", "no_search") else [],
            "contacts": contacts_of(answer),
        }
        _turns.append(turn)
    return turn


def latest(after: int = 0) -> dict | None:
    """after보다 새로운 마지막 턴 (없으면 None)."""
    with _lock:
        return next((t for t in reversed(_turns) if t["seq"] > after), None)
