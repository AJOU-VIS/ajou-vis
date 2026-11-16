"""chunk_context 시험 (외부 라이브러리 불필요). 실행: python3 corpus/scripts/test_chunk_context.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chunk_context import with_context

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(("통과 " if cond else "실패 ") + name)


A = {"rule_name": "아주대학교 학칙", "article_no": "제47조", "article_title": "학사경고, 유급"}
tail = with_context(A, "2. 약학과 : 1, 2학기 전공과목의 평균평점이 2.0 미만인 자")
check("뒷 조각 앞에 규정명·조문 번호·제목이 붙는다", tail.startswith("아주대학교 학칙 제47조(학사경고, 유급) 2. 약학과"))
head = with_context(A, "제47조(학사경고, 유급) ① 학사과정의 경우에는 …")
check("조문 머리말로 시작하는 조각은 머리말을 겹쳐 붙이지 않는다", head == "아주대학교 학칙 제47조(학사경고, 유급) ① 학사과정의 경우에는 …")
check("머리말이 한 번만 있다", head.count("제47조") == 1)
B = {"rule_name": "장학금 지급규칙", "article_no": "제10조", "article_title": "선발자격의 제한"}
check("규정명이 다른 규정의 조각에도 붙는다", with_context(B, "1. 리더장학 …").startswith("장학금 지급규칙 제10조(선발자격의 제한) 1."))
for none in (None, ""):
    check("조항 번호가 없으면(%r) 그대로 둔다" % none, with_context({"rule_name": "x", "article_no": none, "article_title": "t"}, "본문") == "본문")
check("제목이 없으면 번호만 붙인다", with_context({"rule_name": "r", "article_no": "제3조", "article_title": ""}, "본문") == "r 제3조 본문")
check("부칙 조항 번호(길어도)도 붙는다", with_context({"rule_name": "아주대학교 학칙", "article_no": "부칙(2025.1.31., 기획팀-2271호) 제6조", "article_title": "경과조치"}, "② 2024학년도 이전").startswith("아주대학교 학칙 부칙(2025.1.31., 기획팀-2271호) 제6조(경과조치) ②"))

bad = [n for n, ok in checks if not ok]
print("\n전체 %d개 점검 %s" % (len(checks), "통과" if not bad else "중 실패 %d개" % len(bad)))
sys.exit(1 if bad else 0)
