"""rewrite_gate 규칙 단위 시험 (외부 의존 없음). 실행: python3 eval/rewrite_gate/test_gate.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import rewrite_gate as g

SIGNAL = ["그럼 복학은?", "방금 답 영어로 말해줘", "신청 기간은 언제야?", "신청은 어떻게 해?", "환불은?", "거기 몇 시까지 해?",
          "3층은?", "테니스는?", "더 짧게 말해줘", "What GPA puts an undergraduate on academic warning?"]
NO_SIGNAL = ["교내에 CU 편의점은 어디에 있어?", "학사경고는 어떤 경우에 받게 돼?", "개강하고 45일쯤에 휴학하면 등록금 얼마 돌려받아?",
             "무인증명서 발급기는 어디에 있어?", "한 학기에 최대 몇 학점까지 신청할 수 있어?", "기숙사 세탁실은 몇 층이야?"]

bad = [u for u in SIGNAL if g.followup_signal(u) is None] + [u for u in NO_SIGNAL if g.followup_signal(u) is not None]
assert not bad, f"신호 판정이 기대와 다름: {bad}"

assert g.decide("그럼 복학은?", lambda: (_ for _ in ()).throw(AssertionError("신호가 있으면 검색하지 않아야 함")))[0] is True
assert g.decide("무인증명서 발급기는 어디에 있어?", lambda: 0.72, 0.60)[0] is False   # 점수 높음 → 생략
assert g.decide("무인증명서 발급기는 어디에 있어?", lambda: 0.41, 0.60)[0] is True    # 점수 낮음 → 재작성
assert g.enabled(True) is True and g.enabled(False) is False
print("관문 규칙 시험 통과")
