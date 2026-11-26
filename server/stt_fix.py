"""음성 인식 결과 교정 — 검색·재작성·게이트보다 먼저, 반복해서 틀리게 적히는 말만 고친다.

음성 인식이 "CU"를 "시유"로 적으면 자료에 없는 글자라 검색 점수가 기준에 못 미쳐 보류 멘트가
나간다 (10/27 음성 테스트 "씨유" 0.44~0.47, "CU"로 적히면 0.75 · 11/18 지연 측정 "시유" 보류).
"24학번"을 "이사학번"으로 말하면 그대로 "이사학번"으로 적혀 학번을 알아듣지 못한다.

실제 로그에서 두 번 이상 본 오인식만 넣는다. 목록에 없는 말은 건드리지 않으므로 틀리게
고칠 일이 없다. 끄려면 환경변수 STT_FIX=0.
"""
from __future__ import annotations

import os
import re

_ENABLED = os.environ.get("STT_FIX", "1") != "0"

# 조사·문장 끝 앞에서만 고친다 ("시유지" 같은 다른 낱말은 그대로)
_JOSA = r"(?:에서|까지|부터|으로|하고|[은는이가도에의을를로과와랑]){0,2}"
_END = rf"(?={_JOSA}(?:\s|$|[?.!,]))"

# (틀리게 적힌 꼴, 고칠 말) — 주석은 본 날짜
_TERMS = [
    (re.compile(rf"(?<![가-힣])[씨시]유(?:{_END}|(?=편의점))"), "CU"),                     # 10/27 씨유 · 11/18 시유
    (re.compile(r"소원역"), "수원역"),                                                    # 10/27
    (re.compile(r"수원\s영" + _END), "수원역"),                                            # 11/18 두 번
    (re.compile(r"학사\s경호"), "학사경고"),                                               # 11/18
    (re.compile(r"\babout only graduation\b", re.IGNORECASE), "about early graduation"),  # 11/18 두 번
]

# 학번을 한 자리씩 읽은 말: "이사학번" → "24학번", "이공이사 학번" → "2024학번"
_DIGIT = {"공": "0", "영": "0", "일": "1", "이": "2", "삼": "3", "사": "4", "오": "5",
          "육": "6", "칠": "7", "팔": "8", "구": "9"}
_D = "[공영일이삼사오육칠팔구0-9]"
_HAKBEON = re.compile(rf"(?<![가-힣0-9])((?:{_D}\s?){{4}}|(?:{_D}\s?){{2}})학번")


def _hakbeon(m: re.Match) -> str:
    return "".join(_DIGIT.get(ch, ch) for ch in m.group(1) if not ch.isspace()) + "학번"


def fix(text: str) -> str:
    """교정한 문장을 돌려준다. 고칠 것이 없으면 받은 그대로."""
    if not _ENABLED or not text:
        return text
    for pattern, repl in _TERMS:
        text = pattern.sub(repl, text)
    return _HAKBEON.sub(_hakbeon, text)
