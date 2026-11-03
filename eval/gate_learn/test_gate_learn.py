#!/usr/bin/env python3
"""학습형 게이트 시험 코드의 자체 점검 (가짜 LLM·검색기, API·벡터 DB 불필요).

실행:  python3 eval/gate_learn/test_gate_learn.py
숫자는 가짜 데이터라 의미가 없다. 코드가 끝까지 오류 없이, 정의한 대로 도는지만 본다. (scikit-learn 필요)
"""
from __future__ import annotations

import json
import math
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "server"))
import gate_lib as L  # noqa: E402
import gen_data  # noqa: E402
import build_features  # noqa: E402
import train_eval  # noqa: E402
from rag import SearchHit  # noqa: E402

ok_count = 0


def check(name, cond, detail=""):
    global ok_count
    assert cond, "실패: %s %s" % (name, detail)
    ok_count += 1
    print("  OK  " + name)


# ── 1) 작은 함수들 ──
print("[1] 평가 함수")
s, y = [0.9, 0.8, 0.7, 0.2, 0.1], [1, 1, 1, 0, 0]
sk, th, rc = L.skip_at_recall(s, y, 1.0)
check("완전히 분리되면 재현율 100%에서 생략률 100%", (sk, rc) == (1.0, 1.0) and abs(th - 0.7) < 1e-9)
sk, th, rc = L.skip_at_recall([0.9, 0.5, 0.6, 0.2, 0.1], [1, 1, 0, 0, 0], 1.0)
check("섞이면 재현율 100%에서 생략률이 줄어든다 (2/3)", abs(sk - 2 / 3) < 1e-9 and rc == 1.0)
sk, th, rc = L.skip_at_recall([0.9, 0.5, 0.6, 0.2, 0.1], [1, 1, 0, 0, 0], 0.5)
check("재현율 50% 목표면 더 많이 건너뛴다", sk == 1.0 and abs(rc - 0.5) < 1e-9)
check("AUC 완벽=1, 반대=0", L.auc([3, 2, 1, 0], [1, 1, 0, 0]) == 1.0 and L.auc([0, 1, 2, 3], [1, 1, 0, 0]) == 0.0)

# ── 2) 파싱·샘플 변환 ──
print("[2] 생성 결과 파싱")
good = '```json\n{"history":{"user":"휴학은 몇 번 가능해?","assistant":"통산 4년이에요."},"followups":[{"utterance":"신청 기간은?","full_question":"휴학 신청 기간은?","type":"hard"}],"standalone":[{"utterance":"CU는 어디에 있어?"}]}\n```'
g = L.parse_generation(good)
check("코드 블록으로 감싼 JSON도 읽는다", g is not None and len(g["followups"]) == 1 and len(g["standalone"]) == 1)
check("깨진 응답은 None", L.parse_generation("죄송합니다") is None and L.parse_generation('{"history":{"user":""}}') is None)

units = L.load_units()
check("코퍼스 단위를 읽는다(100개 이상)", len(units) >= 100, str(len(units)))
pairs = L.make_pairs(units, 40, seed=1)
check("짝은 서로 다른 문서이고 단위를 재사용하지 않는다",
      all(a["source"] != b["source"] for a, b in pairs) and len({u["uid"] for p in pairs for u in p}) == 2 * len(pairs))
a, b = pairs[0]
samp = L.to_samples(0, a, b, g)
check("꼬리질문 정답은 주제 A, 독립 질문 정답은 주제 B",
      samp[0]["gold_source"] == a["source"] and samp[1]["gold_source"] == b["source"] and samp[1]["full_question"] == samp[1]["utterance"])

# ── 3) 가짜 LLM / 검색기 / 임베더 ──
def bigrams(t):
    t = re.sub(r"\s", "", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


class FakeIndex:
    def __init__(self, units):
        self.units = units
        self.grams = [bigrams(u["article"] + " " + u["text"]) for u in units]

    def search(self, q, top_k=5):
        g = bigrams(q)
        scored = []
        for u, ug in zip(self.units, self.grams):
            if g:
                scored.append((0.35 + 0.5 * len(g & ug) / len(g), u))
        scored.sort(key=lambda x: -x[0])
        return [SearchHit(source_name=u["source"], article=u["article"], text="", score=sc) for sc, u in scored[:top_k]]


def fake_embed(texts):
    out = []
    for t in texts:
        v = [0.0] * 128
        for gram in bigrams(t):
            v[hash(gram) % 128] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


calls = {"n": 0}
BAD_CALL = 3


def fake_chat(system, user, max_tokens):
    calls["n"] += 1
    m = re.search(r"\[주제 A\] 출처: (.*?) / (.*?)\n.*?\[주제 B\] 출처: (.*?) / (.*?)\n", user, re.S)
    A_title, B_title = m.group(2), m.group(4)
    if "c3-marker" in user:
        return "죄송합니다"
    if calls["n"] == 5:                 # 한 번은 깨진 응답 → 재시도로 복구되는지
        return "{깨짐"
    # 생략형 1개(지금 규칙이 신호로 잡는다) + 모호 명사형 2개(다른 주제 B의 이름을 단 발화 — 규칙이 못 잡고, 그대로 검색하면 B가 나온다)
    fol = [{"utterance": "신청 기간은 언제까지야?", "full_question": "%s 신청 기간은 언제까지야?" % A_title, "type": "elliptical"},
           {"utterance": "%s 쪽은 어떻게 돼요" % B_title, "full_question": "%s 중에서 %s 쪽은 어떻게 돼요" % (A_title, B_title), "type": "ambiguous"},
           {"utterance": "%s 관련해서는 뭐가 달라져" % B_title, "full_question": "%s의 경우 %s 관련해서는 뭐가 달라져" % (A_title, B_title), "type": "ambiguous"}]
    sta = [{"utterance": "%s에 대해 알려줘" % B_title}, {"utterance": "%s 기준이 어떻게 돼?" % B_title}, {"utterance": "%s 신청은 어떻게 해?" % B_title}]
    return json.dumps({"history": {"user": "%s에 대해 알려줘" % A_title, "assistant": "문서에 따르면 정해져 있어요."}, "followups": fol, "standalone": sta}, ensure_ascii=False)


print("[3] 생성(이어하기·재시도)")
tmp = Path(tempfile.mkdtemp())
sp = tmp / "samples.jsonl"
pairs60 = L.make_pairs(units, 60, seed=2)
ok, bad = gen_data.generate(pairs60, fake_chat, sp, log=lambda *_: None)
n_lines = sum(1 for _ in open(sp, encoding="utf-8"))
check("60호출이 모두 성공하고 샘플이 약 360개", ok == 60 and bad == 0 and 340 <= n_lines <= 360, "%d %d %d" % (ok, bad, n_lines))
ok2, bad2 = gen_data.generate(pairs60, fake_chat, sp, log=lambda *_: None)
check("같은 명령을 다시 실행하면 이미 만든 호출은 건너뛴다", ok2 == 0 and bad2 == 0 and sum(1 for _ in open(sp, encoding="utf-8")) == n_lines)

# ── 4) 라벨·특징 ──
print("[4] 라벨과 특징")
samples = [json.loads(l) for l in open(sp, encoding="utf-8")]
idx = FakeIndex(units)
rows, dropped = build_features.build_rows(samples, idx.search, fake_embed, 5, log=lambda *_: None)
check("신호가 있는 발화도 signal=1로 남는다", len(rows) == len(samples) and dropped == sum(r["signal"] for r in rows) and 0 < dropped < len(rows))
nosig = [r for r in rows if not r["signal"]]
check("라벨은 -1/0/1뿐이고 특징에 NaN이 없다",
      all(r["label"] in (-1, 0, 1) for r in rows) and all(not math.isnan(r[f]) for r in rows for f in L.FEATURES))
by = {v: sum(1 for r in nosig if r["label"] == v) for v in (-1, 0, 1)}
check("신호 없는 발화에서 라벨 0과 1이 모두 나온다(검색기가 정말 구분해 준다)", by[0] > 0 and by[1] > 0, str(by))

# 라벨 정의를 직접 만든 검색 결과로 확인
mk = lambda s, a: SearchHit(source_name=s, article=a, text="", score=0.6)
def mkrow(raw_hits, full_hits):
    def search(q): return raw_hits if q == "발화" else (full_hits if q == "풀이" else [mk("딴", "딴")])
    sample = {"id": "t", "call": 0, "type": "followup", "history": [{"role": "user", "content": "이전"}, {"role": "assistant", "content": "답"}],
              "utterance": "발화", "full_question": "풀이", "gold_source": "A", "gold_article": "a"}
    return L.compute_row(sample, search, fake_embed, 5)
check("라벨 1: 그대로는 못 찾고 풀어 쓰면 찾는다", mkrow([mk("딴", "x")], [mk("A", "a")])["label"] == 1)
check("라벨 0: 그대로 찾는다", mkrow([mk("A", "a")], [mk("A", "a")])["label"] == 0)
check("라벨 -1: 풀어 써도 못 찾으면 모호", mkrow([mk("딴", "x")], [mk("딴", "y")])["label"] == -1)

# ── 5) 학습·평가 (외부 시험 세트 포함) ──
print("[5] 학습·평가")
ext_path = HERE.parents[1] / "eval" / "rewrite_gate" / "cases.json"
ext = build_features.load_external(ext_path) if ext_path.exists() else []
ext_rows, _ = build_features.build_rows(ext, idx.search, fake_embed, 5, log=lambda *_: None)
fp = tmp / "features.csv"
build_features.write_csv(rows + ext_rows, fp)
loaded = train_eval.load_rows(fp)
summary = train_eval.run(loaded, tmp / "out", log=lambda *_: None)
summary_all = train_eval.run(loaded, tmp / "out_all", population="all", log=lambda *_: None)
check("대상 선택: 전체 발화가 신호 없는 발화보다 많다", summary_all["n"] > summary["n"], "%d vs %d" % (summary_all["n"], summary["n"]))
check("보고서와 예측 파일이 만들어진다", (tmp / "out" / "report.md").exists() and (tmp / "out" / "oof_predictions.csv").exists())
check("같은 재현율 표의 생략률은 0~1이다", all(0.0 <= v <= 1.0 for t in summary["table"].values() for v in t.values() if not math.isnan(v)))
check("AUC가 계산된다", all(0.0 <= v <= 1.0 for v in summary["auc"].values()))
if ext:
    check("외부 확인이 실행된다", "external" in summary and 0 <= summary["external"]["skip_lr"] <= 1)
print("\n전체 %d개 점검 통과" % ok_count)
