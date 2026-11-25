"""stt_fix 의 교정 규칙 점검. 서버·검색 DB 없이 돈다.
실행: python server/test_stt_fix.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stt_fix

fails = 0
total = 0
def check(heard, expected):
    global fails, total
    total += 1
    got = stt_fix.fix(heard)
    ok = got == expected
    print(("통과 " if ok else "실패 ") + f"{heard!r} → {got!r}" + ("" if ok else f" (기대 {expected!r})"))
    fails += 0 if ok else 1

# 1. 고유명사: 로그에서 본 꼴
check("시유 어디에 있어?", "CU 어디에 있어?")                      # 11/18
check("씨유는 어디야?", "CU는 어디야?")                            # 10/27
check("학교 안에 씨유편의점 있어?", "학교 안에 CU편의점 있어?")
check("수원 영에서는?", "수원역에서는?")                           # 11/18
check("소원역 셔틀 첫차 몇 시야?", "수원역 셔틀 첫차 몇 시야?")     # 10/27
check("학사 경호 기준이 뭐야?", "학사경고 기준이 뭐야?")            # 11/18
check("What about only graduation?", "What about early graduation?")

# 2. 학번을 한 자리씩 읽은 말
check("소프트웨어학과 이사학번은?", "소프트웨어학과 24학번은?")
check("이사 학번 졸업학점 알려줘", "24학번 졸업학점 알려줘")
check("일구학번은 몇 학점이야?", "19학번은 몇 학점이야?")
check("이공이사학번인데 졸업요건이 뭐야?", "2024학번인데 졸업요건이 뭐야?")
check("2사학번은?", "24학번은?")

# 3. 건드리면 안 되는 말
for same in [
    "CU 어디에 있어?",
    "24학번은 졸업하려면 몇 학점 필요해?",
    "이십사학번은 몇 학점이야?",
    "기숙사로 이사 가려면 어떻게 해?",
    "이사 가는데 학번이 필요해?",
    "시유지 관련 규정 있어?",
    "다시 유학생 장학금 알려줘",
    "수원역에서 어떻게 가?",
    "수원 영통에서 버스 타면 돼?",
    "학사경고 기준이 뭐야?",
    "Is this the only graduation requirement?",
    "",
]:
    check(same, same)

print(f"\n{total - fails}/{total} 통과")
sys.exit(1 if fails else 0)
