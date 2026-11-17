"""add_sibling_chunks 시험 (chromadb·모델 불필요). 실행: python3 server/test_rag_siblings.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rag import add_sibling_chunks

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(("통과 " if cond else "실패 ") + name)


def M(rule, art, idx):
    return {"rule_id": rule, "article_no": art, "chunk_index": idx}


DB = {
    ("r288", "제10조"): [("제10조 ② 예외 …", M("r288", "제10조", 1)), ("제10조 ① 복학생 …", M("r288", "제10조", 0))],
    ("r594", "제47조"): [("제47조 ① 1.75 …", M("r594", "제47조", 0)), ("제47조 2. 약학과 …", M("r594", "제47조", 1)), ("제47조 나. F학점 …", M("r594", "제47조", 2))],
}
calls = []


def fetch(rule, art):
    calls.append((rule, art))
    return DB.get((rule, art), [])


tail = ("제10조 ② 예외 …", M("r288", "제10조", 1), 0.65, False)
out = add_sibling_chunks([tail], fetch)
check("걸린 조각의 같은 조문 이웃(①항)이 뒤에 붙는다", [r[0] for r in out] == ["제10조 ② 예외 …", "제10조 ① 복학생 …"])
check("이웃 점수는 원래보다 낮아 최고점이 그대로다", max(r[2] for r in out) == 0.65 and out[1][2] < 0.65)
check("이미 들어 있는 조각은 중복해서 붙이지 않는다", len(add_sibling_chunks(out, fetch)) == len(out))

page = ("유학생 FAQ …", {"rule_id": "web_x", "article_no": "", "chunk_index": 0}, 0.6, False)
calls.clear()
check("조항 번호가 없는 안내 페이지·시설은 건드리지 않는다", add_sibling_chunks([page], fetch) == [page] and not calls)

many = [("제47조 2. 약학과 …", M("r594", "제47조", 1), 0.68, False)]
out = add_sibling_chunks(many, fetch)
check("붙이는 개수에 상한이 있다(기본 2)", len(out) - 1 == 2)
check("chunk_index 순서로 붙는다(①항이 먼저)", out[1][0].startswith("제47조 ① "))
two = [tail, ("제47조 2. 약학과 …", M("r594", "제47조", 1), 0.64, False)]
check("여러 조문이 걸려도 전체 상한을 넘지 않는다", len(add_sibling_chunks(two, fetch)) - 2 <= 2)
check("max_extra=0이면 아무것도 붙지 않는다", add_sibling_chunks([tail], fetch, max_extra=0) == [tail])
check("이웃이 없으면 그대로", add_sibling_chunks([("x", M("r1", "제1조", 0), 0.5, False)], fetch)[0][0] == "x")

bad = [n for n, ok in checks if not ok]
print("\n전체 %d개 점검 %s" % (len(checks), "통과" if not bad else "중 실패 %d개" % len(bad)))
sys.exit(1 if bad else 0)
