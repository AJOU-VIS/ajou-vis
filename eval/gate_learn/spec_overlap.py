#!/usr/bin/env python3
"""추측 실행이 재작성을 얼마나 자주 기다리지 않아도 되는지 잰다 (API 호출 없음, 이미 만든 재작성 결과를 쓴다).

추측 실행: 재작성과 '발화 그대로 검색한 문서로 답변 생성'을 동시에 시작하고, 재작성이 끝났을 때
  - 재작성 결과로 검색한 상위 K개 문서가 이미 시작한 것과 같으면 그 답변을 그대로 쓴다 (재작성 시간 약 0.9초를 숨긴다)
  - 다르면 취소하고 재작성 결과로 다시 시작한다 (지금과 같은 시간 + 낭비된 호출 1회)
그래서 '문서가 같은 비율'이 곧 절감 가능한 비율의 상한이다.

실행 (저장소 루트, 벡터 DB가 있는 환경):
  server/.venv/bin/python eval/gate_learn/spec_overlap.py \
      --samples eval/gate_learn/data/samples_v2.jsonl --cache eval/gate_learn/data/rewrite_cache_v2.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_lib as L  # noqa: E402


def docs(hits, k):
    out = []
    for h in list(hits)[:k]:
        key = (h.source_name, h.article)
        if key not in out:
            out.append(key)
    return out


def run(samples, cache, search, k: int = 5, log=print):
    rows = []
    for s in samples:
        if L.rewrite_gate.followup_signal(s["utterance"]) is not None:
            continue                                        # 신호가 있으면 어차피 재작성하므로 추측할 이유가 없다
        rw = cache.get(s["id"])
        if rw is None:
            continue
        raw = docs(search(s["utterance"]), k)
        new = raw if rw == s["utterance"] else docs(search(rw), k)
        rows.append({"type": s["type"], "same_text": rw == s["utterance"], "same_set": set(raw) == set(new),
                     "inter": len(set(raw) & set(new)), "n": max(1, len(set(raw)))})
    pct = lambda a, b: "%.0f%% (%d/%d)" % (100.0 * a / b, a, b) if b else "-"
    lines = ["# 추측 실행 가능성: 재작성 전후 검색 문서의 겹침 (신호 없는 발화, 상위 %d개)" % k, "",
             "| 종류 | 샘플 | 재작성이 발화를 안 바꿈 | **상위 문서 집합이 같음** | 4개 이상 겹침 | 3개 이상 겹침 |", "|---|---|---|---|---|---|"]
    stat = {}
    for name, sel in (("독립 질문", lambda r: r["type"] == "standalone"), ("꼬리질문", lambda r: r["type"] == "followup"), ("전체", lambda r: True)):
        rs = [r for r in rows if sel(r)]
        n = len(rs)
        a = sum(r["same_text"] for r in rs)
        b = sum(r["same_set"] for r in rs)
        c = sum(r["inter"] >= min(4, r["n"]) for r in rs)
        d = sum(r["inter"] >= min(3, r["n"]) for r in rs)
        stat[name] = (n, a, b, c, d)
        lines.append("| %s | %d | %s | **%s** | %s | %s |" % (name, n, pct(a, n), pct(b, n), pct(c, n), pct(d, n)))
    lines += ["", "## 읽는 법", "",
              "- **'상위 문서 집합이 같음'**이 추측 실행으로 재작성 시간(약 0.9초)을 숨길 수 있는 비율의 상한이다. 독립 질문에서 높고 꼬리질문에서 낮아야 이치에 맞다.",
              "- 같지 않은 경우는 취소하고 다시 시작하므로 지금과 같은 시간이 걸리고, 답변 생성 호출 1회가 낭비된다(비용).",
              "- '4개 이상 겹침'은 문서 하나쯤 다르더라도 답이 같다고 보는 느슨한 기준이다. 쓰려면 별도로 답변 품질을 확인해야 한다.",
              "- 실제 절감은 이 비율 × 재작성 시간이다. 병렬 실행의 지연(스레드·네트워크)과 취소 처리 비용은 포함하지 않았다."]
    text = "\n".join(lines)
    log(text)
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(HERE / "data" / "samples_v2.jsonl"))
    ap.add_argument("--cache", default=str(HERE / "data" / "rewrite_cache_v2.json"))
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--out", default=str(HERE / "out_v2" / "spec_overlap.md"))
    a = ap.parse_args()
    import build_features as B
    search, _ = B.load_retriever()
    samples = [json.loads(l) for l in open(a.samples, encoding="utf-8") if l.strip()]
    cache = json.loads(Path(a.cache).read_text(encoding="utf-8"))
    buf = []
    run(samples, cache, search, a.topk, log=lambda t: (print(t), buf.append(t)))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(buf), encoding="utf-8")
    print("\n저장:", a.out)


if __name__ == "__main__":
    main()
