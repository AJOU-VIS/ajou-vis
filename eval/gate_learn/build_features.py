#!/usr/bin/env python3
"""2단계: 샘플마다 검색을 돌려 라벨과 특징을 계산한다 (LLM 호출 없음, 과금 없음).

샘플 하나당 검색 3번(발화, 독립 질문, 이전 질문)과 임베딩 몇 번이 들어간다. BGE-M3를 CPU로 돌리면 700개에 5~10분 걸린다.
신호(그럼·거기·영어로 등)가 있어 이미 재작성으로 가는 발화는 signal=1로 표시한다. 학습·평가의 기본 대상은 signal=0(신호 없는 발화)이다.
직접 만든 시험 세트(eval/rewrite_gate/cases.json)도 '외부 확인용'으로 같이 계산한다.

실행 (저장소 루트, 서버 가상환경, 벡터 DB가 있는 환경):
  server/.venv/bin/python eval/gate_learn/build_features.py
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_lib as L  # noqa: E402

COLS = (["id", "call", "type", "difficulty", "external", "signal", "label", "label_oracle", "label_real", "raw_hit", "full_hit", "real_hit", "raw_hit_page"] + L.FEATURES +
        ["gold", "raw_top3", "utterance", "rewritten", "full_question", "prev_question"])


def load_retriever():
    sys.path.insert(0, str(L.ROOT / "server"))
    from rag import ChromaRetriever  # noqa: E402

    db = L.ROOT / "corpus" / "chroma_db"
    if not db.exists():
        raise SystemExit("벡터 DB가 없습니다: %s (corpus/scripts/embed_corpus.py를 먼저 실행)" % db)
    r = ChromaRetriever(db)
    r._ensure_loaded()
    return (lambda q: r.search(q)), (lambda texts: r._model.encode(list(texts), normalize_embeddings=True))


def load_external(path: Path):
    """직접 만든 시험 세트에서 꼬리질문·독립 질문만 (형태 변경 요청은 신호가 이미 걸러서 제외)."""
    out = []
    for i, c in enumerate(json.loads(path.read_text(encoding="utf-8"))["cases"]):
        if c["label"] not in ("followup", "standalone"):
            continue
        msgs = c["messages"]
        out.append({"id": "X-" + c["id"], "call": -1 - i, "type": c["label"], "difficulty": "hand", "external": True,
                    "history": msgs[:-1], "utterance": c["utterance"],
                    "full_question": c.get("expected_question") or c["utterance"]})
    return out


def build_rows(samples, search, embed, k: int = 5, rewrite_fn=None, log=print):
    rows = []
    t0 = time.time()
    for i, s in enumerate(samples):
        rows.append(L.compute_row(s, search, embed, k, None if s.get("external") else rewrite_fn))   # 신호 있는 발화도 계산해 signal 열로 표시
        if (i + 1) % 50 == 0:
            log("  %d/%d (%.0f초)" % (i + 1, len(samples), time.time() - t0))
    return rows, sum(r["signal"] for r in rows)


def write_csv(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:     # utf-8-sig: 엑셀·넘버스에서 한글이 안 깨진다
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(HERE / "data" / "samples.jsonl"))
    ap.add_argument("--external", default=str(L.ROOT / "eval" / "rewrite_gate" / "cases.json"))
    ap.add_argument("--out", default=str(HERE / "data" / "features.csv"))
    ap.add_argument("--topk", type=int, default=5, help="정답 문서가 들어 있어야 하는 상위 개수 (서버가 LLM에 넘기는 수)")
    ap.add_argument("--review", type=int, default=30, help="사람이 훑어볼 샘플 수")
    ap.add_argument("--rewrite", choices=["real", "oracle"], default="real",
                    help="real: 서버의 실제 재작성기로 라벨을 만든다(Claude 호출 약 600회, 약 $0.5, 10분 안팎). oracle: LLM이 써 준 풀어 쓴 질문으로 만든다(무료)")
    ap.add_argument("--model", default="claude-haiku-4-5", help="재작성에 쓸 모델 (지연 측정에 쓴 설정과 같게)")
    ap.add_argument("--cache", default=str(HERE / "data" / "rewrite_cache.json"), help="재작성 결과 저장 파일(끊겨도 이어서 한다)")
    args = ap.parse_args()

    samples = [json.loads(l) for l in open(args.samples, encoding="utf-8") if l.strip()]
    ext = load_external(Path(args.external)) if Path(args.external).exists() else []
    print("생성 샘플 %d개 + 외부 확인용 %d개" % (len(samples), len(ext)))
    search, embed = load_retriever()
    rewrite_fn = None
    if args.rewrite == "real":
        import os
        os.environ["LLM_MODEL"] = args.model                # llm 모듈이 import 시점에 읽는다
        try:
            from dotenv import load_dotenv
            load_dotenv(L.ROOT / "server" / ".env", override=False)
        except ImportError:
            pass
        import llm  # noqa: E402
        cache_path = Path(args.cache)
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        real = L.make_real_rewriter(llm.chat)
        stat = {"new": 0, "err": 0}

        def rewrite_fn(sample):
            if sample["id"] in cache:
                return cache[sample["id"]]
            try:
                out = real(sample)
            except Exception as e:                         # 한 번의 실패가 전체를 멈추지 않게 (원문 그대로 둔다)
                stat["err"] += 1
                print("  재작성 호출 오류(%s): %s" % (type(e).__name__, sample["id"]))
                return sample["utterance"]
            cache[sample["id"]] = out
            stat["new"] += 1
            if stat["new"] % 25 == 0:
                cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            return out
        print("실제 재작성기로 라벨을 만듭니다 (모델 %s, 캐시 %d개)" % (args.model, len(cache)))
    rows, dropped = build_rows(samples + ext, search, embed, args.topk, rewrite_fn)
    if rewrite_fn is not None:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print("재작성 호출 새로 %d회, 오류 %d회" % (stat["new"], stat["err"]))
    print("계산 %d개 (그중 지금 규칙이 신호로 이미 잡는 발화 %d개, 신호 없는 발화 %d개)" % (len(rows), dropped, len(rows) - dropped))
    write_csv(rows, Path(args.out))

    internal = [r for r in rows if not r["external"] and not r["signal"]]      # 신호 없는 발화만 집계
    cnt = {v: sum(1 for r in internal if r["label"] == v) for v in (1, 0, -1)}
    print("\n라벨 (생성 샘플 중 신호 없는 발화, %s 기준): 재작성 필요 %d · 건너뛰어도 됨 %d · 모호(제외) %d" % (
        "실제 재작성기" if args.rewrite == "real" else "LLM이 쓴 풀어 쓴 질문", cnt[1], cnt[0], cnt[-1]))
    if args.rewrite == "real":
        o = {v: sum(1 for r in internal if r["label_oracle"] == v) for v in (1, 0, -1)}
        print("  (참고) LLM이 쓴 풀어 쓴 질문 기준이면: 필요 %d · 건너뜀 %d · 모호 %d" % (o[1], o[0], o[-1]))
    for t in ("followup", "standalone"):
        sub = [r for r in internal if r["type"] == t]
        print("  %-10s %3d개: 필요 %d · 건너뜀 %d · 모호 %d" % (t, len(sub), *(sum(1 for r in sub if r["label"] == v) for v in (1, 0, -1))))
    print("저장:", args.out)

    # 사람이 라벨을 훑어볼 표 (LLM이 만든 데이터라 직접 읽어서 어색한 것이 많은지 확인해야 한다)
    rnd = random.Random(3)
    pick = rnd.sample([r for r in internal if r["label"] in (0, 1)], min(args.review, len(internal)))
    rev = Path(args.out).with_name(Path(args.out).stem.replace("features", "review") + ".csv")   # features.csv → review.csv, features_v2.csv → review_v2.csv
    with rev.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "종류", "이전 질문", "발화", "LLM이 쓴 풀어 쓴 질문", "실제 재작성기 결과", "정답 문서", "발화 그대로 검색한 상위3", "라벨(1=재작성 필요)", "사람 확인(OK/이상)"])
        for r in pick:
            w.writerow([r["id"], r["type"], r["prev_question"], r["utterance"], r["full_question"], r["rewritten"], r["gold"], r["raw_top3"], r["label"], ""])
    print("훑어볼 표:", rev)


if __name__ == "__main__":
    main()
