"""재작성 우회 관문 평가 (오프라인, LLM 호출 없음 — 과금 없음).

시험 세트(cases.json)의 각 발화에 대해 관문이 "재작성 호출 / 생략"을 어떻게 판단하는지 보고,
기준 점수 τ(TAU)를 바꿔가며 두 가지를 잰다.
  재현율  꼬리질문·형태 변경 요청(재작성이 꼭 필요한 발화) 중 실제로 재작성으로 보낸 비율 — 놓치면 오답이므로 100%에 가깝게
  생략률  독립 질문(재작성 불필요) 중 건너뛴 비율 — 높을수록 시간이 줄어든다
τ는 dev 절반에서 "재현율 100%를 지키는 가장 낮은 값"으로 고르고, test 절반에서 확인한다(과적합 점검).

실행 (저장소 루트, 벡터 DB가 있는 환경):
  server/.venv/bin/python eval/rewrite_gate/run_eval.py
  server/.venv/bin/python eval/rewrite_gate/run_eval.py --taus 0.5,0.55,0.6,0.65,0.7 --json eval/rewrite_gate/results.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
import rewrite_gate  # noqa: E402

NEED_REWRITE = ("followup", "format")   # 재작성이 필요한 종류
REWRITE_SEC = 0.89                       # 측정한 재작성 중앙값(초) — 예상 절감 계산용


def build_search_fn():
    """실제 검색기로 (최고 점수, 상위 3개 출처 이름)을 돌려주는 함수를 만든다."""
    from rag import ChromaRetriever  # noqa: E402

    db = ROOT / "corpus" / "chroma_db"
    if not db.exists():
        raise SystemExit(f"벡터 DB가 없습니다: {db} (corpus/scripts/embed_corpus.py를 먼저 실행)")
    retriever = ChromaRetriever(db)

    def search(utterance: str):
        hits = retriever.search(utterance)
        top = max((h.score for h in hits), default=0.0)
        return top, [h.source_name for h in hits[:3]]

    return search


def probe(cases: list[dict], search_fn) -> list[dict]:
    """발화마다 신호·최고 점수·상위 출처를 한 번씩만 계산한다."""
    rows = []
    for c in cases:
        top, sources = search_fn(c["utterance"])
        gold_hit = None if not c["gold_docs"] else any(g in s for g in c["gold_docs"] for s in sources)
        rows.append({**{k: c[k] for k in ("id", "label", "split", "utterance")},
                     "signal": rewrite_gate.followup_signal(c["utterance"]),
                     "score": top, "sources": sources, "gold_hit": gold_hit})
    return rows


def decision(row: dict, tau: float) -> bool:
    """True = 재작성 호출. 신호가 있거나 점수가 τ 미만이면 재작성."""
    return bool(row["signal"]) or row["score"] < tau


def metrics(rows: list[dict], tau: float) -> dict:
    need = [r for r in rows if r["label"] in NEED_REWRITE]
    stand = [r for r in rows if r["label"] == "standalone"]
    recall = sum(decision(r, tau) for r in need) / len(need) if need else None
    skipped = [r for r in stand if not decision(r, tau)]
    judged = [r for r in skipped if r["gold_hit"] is not None]
    return {
        "tau": tau, "n_need": len(need), "n_stand": len(stand),
        "recall": recall,
        "missed": [r["id"] for r in need if not decision(r, tau)],
        "skip_rate": len(skipped) / len(stand) if stand else None,
        "skipped_gold_hit": (sum(r["gold_hit"] for r in judged) / len(judged)) if judged else None,
        "est_saving_sec": (len(skipped) / len(stand) * REWRITE_SEC) if stand else None,
    }


def pct(x):
    return "-" if x is None else f"{x:.0%}"


def main():
    ap = argparse.ArgumentParser(description="재작성 우회 관문 평가")
    ap.add_argument("--cases", default=str(Path(__file__).with_name("cases.json")))
    ap.add_argument("--taus", default="0.45,0.50,0.55,0.60,0.65,0.70,0.75")
    ap.add_argument("--json", help="결과를 저장할 json 경로")
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    taus = [float(x) for x in args.taus.split(",")]
    rows = probe(cases, build_search_fn())
    dev = [r for r in rows if r["split"] == "dev"]
    test = [r for r in rows if r["split"] == "test"]

    print(f"시험 세트 {len(rows)}개 (꼬리질문+형태 {sum(r['label'] in NEED_REWRITE for r in rows)}, 독립 {sum(r['label'] == 'standalone' for r in rows)})")
    print("\n[1] 신호만으로 이미 재작성으로 보내는 발화 (검색 점수와 무관)")
    for lab in ("followup", "format", "standalone"):
        sub = [r for r in rows if r["label"] == lab]
        print(f"  {lab:<10} {sum(bool(r['signal']) for r in sub)}/{len(sub)}")

    print("\n[2] τ별 결과 — 재현율(꼬리·형태) / 독립 질문 생략률 / 생략한 질문의 검색 적중 / 예상 절감(생략률×0.89초)")
    print("    τ  |  dev 재현율  생략률 |  test 재현율  생략률 | 전체 재현율  생략률  적중  예상절감 | 놓친 꼬리질문")
    table = []
    for tau in taus:
        md, mt, ma = metrics(dev, tau), metrics(test, tau), metrics(rows, tau)
        table.append({"tau": tau, "dev": md, "test": mt, "all": ma})
        print(f"  {tau:.2f} |   {pct(md['recall']):>5}  {pct(md['skip_rate']):>6} |    {pct(mt['recall']):>5}   {pct(mt['skip_rate']):>6} |"
              f"    {pct(ma['recall']):>5}   {pct(ma['skip_rate']):>6} {pct(ma['skipped_gold_hit']):>5}   {ma['est_saving_sec']:.2f}초 | {', '.join(ma['missed']) or '-'}")

    # τ 선택: dev 재현율 100%를 지키는 가장 낮은 τ (없으면 dev 재현율이 가장 높은 것 중 가장 낮은 τ)
    full = [t for t in table if t["dev"]["recall"] == 1.0]
    chosen = (min(full, key=lambda t: t["tau"]) if full
              else max(table, key=lambda t: (t["dev"]["recall"], -t["tau"])))
    c = chosen["tau"]
    print(f"\n[3] 선택한 τ = {c:.2f}  ({'dev 재현율 100%를 지키는 가장 낮은 값' if full else 'dev에서 100%를 지키는 τ가 없어 재현율이 가장 높은 값'})")
    print(f"    test 확인: 재현율 {pct(chosen['test']['recall'])} · 생략률 {pct(chosen['test']['skip_rate'])} · 놓친 꼬리질문 {chosen['test']['missed'] or '-'}")

    print(f"\n[4] τ={c:.2f}에서 짚어볼 발화")
    for r in rows:
        dec = decision(r, c)
        need = r["label"] in NEED_REWRITE
        flag = ""
        if need and not dec:
            flag = "❌ 꼬리질문인데 건너뜀(오답 위험)"
        elif (not need) and dec:
            flag = "△ 독립 질문인데 재작성(시간 손해)"
        if flag:
            why = r["signal"] or f"점수 {r['score']:.2f}"
            print(f"  {r['id']} [{r['split']}] {r['utterance'][:36]!r:<40} {flag} · 이유: {why} · 상위: {r['sources'][:1]}")

    print("\n[5] 검색 점수 분포 (신호 없는 발화)")
    for lab in ("followup", "format", "standalone"):
        sc = [r["score"] for r in rows if r["label"] == lab and not r["signal"]]
        if sc:
            print(f"  {lab:<10} n={len(sc):>2} · 최저 {min(sc):.2f} · 중앙 {statistics.median(sc):.2f} · 최고 {max(sc):.2f}")

    if args.json:
        Path(args.json).write_text(json.dumps({"chosen_tau": c, "table": table, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n저장: {args.json}")


if __name__ == "__main__":
    main()
