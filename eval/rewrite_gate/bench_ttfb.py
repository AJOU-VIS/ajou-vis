"""RAG 서버에 시험 세트를 직접 보내 '요청 → 첫 글자' 시간을 재서, 재작성 관문 설정을 비교한다 (음성 필요 없음).

설정(arm): off(관문 끔 = 지금 방식), 숫자(관문 켬, 기준 점수 τ). 예: off,0.75,0.70,0.65
서버는 요청 본문의 rewrite_gate / rewrite_gate_tau로 요청마다 설정을 바꿀 수 있어서, 같은 서버에 설정들을 번갈아 보내
네트워크·캐시 영향을 줄인다. 서버는 응답 헤더 X-Rewrite-Skip으로 재작성을 건너뛰었는지 알려준다.
Claude API를 실제로 호출하므로 비용이 든다 (40개 × 설정 수, 모델에 따라 약 $0.3~0.6).

실행 (서버와 같은 기기에서 — Colab이면 새 코드 셀에서 !python …):
  python eval/rewrite_gate/bench_ttfb.py --url http://127.0.0.1:8100/v1/chat/completions
  python eval/rewrite_gate/bench_ttfb.py --url ... --arms off,0.70 --repeat 2 --out bench_result.json
의존 패키지 없음(표준 라이브러리만).
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

DEFER = ("죄송", "자료에 없", "확실하지", "알 수 없", "확인해 주세요", "문의", "어려워요")


def payload(messages: list[dict], arm: str) -> dict:
    body = {"model": "ajou-vis", "stream": True, "messages": messages}
    if arm == "off":
        body["rewrite_gate"] = False
    else:
        body["rewrite_gate"] = True
        body["rewrite_gate_tau"] = float(arm)
    return body


def ask(url: str, messages: list[dict], arm: str, timeout: float = 60.0):
    """(첫 글자까지 초, 전체 초, 답변 앞부분, 재작성 생략 여부)를 돌려준다."""
    req = urllib.request.Request(url, data=json.dumps(payload(messages, arm)).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    text = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        skip_hdr = resp.headers.get("X-Rewrite-Skip")
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
            except (KeyError, IndexError, ValueError):
                continue
            if delta:
                if first is None:
                    first = time.perf_counter() - t0
                text.append(delta)
    return first, time.perf_counter() - t0, "".join(text), (None if skip_hdr is None else skip_hdr == "1")


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def f2(x):
    return "-" if x is None else f"{x:.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8100/v1/chat/completions")
    ap.add_argument("--cases", default=str(Path(__file__).with_name("cases.json")))
    ap.add_argument("--arms", default="off,0.75,0.70,0.65", help="비교할 설정 (쉼표). off 또는 기준 점수")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", help="label만 (followup, format, standalone)")
    ap.add_argument("--warmup", type=int, default=2, help="결과에서 버릴 앞쪽 요청 수(모델·연결 예열)")
    ap.add_argument("--out", help="결과 json 저장 경로")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    assert "off" in arms, "비교 기준이 되는 off가 arms에 있어야 합니다"
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if c["label"] == args.only]

    for c in cases[:args.warmup]:          # 예열 (결과에서 제외)
        ask(args.url, c["messages"], "off")

    rows = []
    k = 0
    for rep in range(args.repeat):
        for c in cases:
            shift = k % len(arms)          # 설정 순서를 돌려가며 보내 순서 편향을 줄인다
            k += 1
            res = {}
            for arm in arms[shift:] + arms[:shift]:
                try:
                    f, t, text, skipped = ask(args.url, c["messages"], arm)
                    res[arm] = {"first": f, "total": t, "text": text[:80], "skipped": skipped}
                except Exception as e:     # 한 건 실패가 전체를 멈추지 않게
                    res[arm] = {"first": None, "total": None, "text": f"(오류: {type(e).__name__})", "skipped": None}
            rows.append({"id": c["id"], "label": c["label"], "rep": rep, "arms": res})
            print("  " + f"{c['id']} {c['label']:<10} " + " · ".join(f"{a} {f2(res[a]['first'])}s{'*' if res[a]['skipped'] else ''}" for a in arms))
    print("  (* = 재작성 생략)")

    print("\n=== 요청 → 첫 글자, 중앙값 (초) ===")
    print("설정      " + "  ".join(f"{lab:>10}" for lab in ("followup", "format", "standalone", "전체")))
    base = {}
    for arm in arms:
        cells = []
        for lab in ("followup", "format", "standalone", "전체"):
            sub = rows if lab == "전체" else [r for r in rows if r["label"] == lab]
            m = med([r["arms"][arm]["first"] for r in sub])
            if arm == "off":
                base[lab] = m
            cells.append(f"{f2(m):>10}")
        print(f"{arm:<8}  " + "  ".join(cells))
    print("\n=== off 대비 절감 (초, 중앙값) · 재작성을 건너뛴 요청 수 ===")
    for arm in arms:
        if arm == "off":
            continue
        out = []
        for lab in ("standalone", "followup", "format"):
            sub = [r for r in rows if r["label"] == lab]
            m = med([r["arms"][arm]["first"] for r in sub])
            sk = sum(bool(r["arms"][arm]["skipped"]) for r in sub)
            out.append(f"{lab} {f2((base[lab] - m) if (base.get(lab) and m) else None)} (생략 {sk}/{len(sub)})")
        print(f"τ={arm:<5} " + " · ".join(out))

    print("\n=== 꼬리질문·형태 변경인데 재작성을 건너뛴 사례 (오답 위험 — 답변을 직접 확인) ===")
    for arm in arms:
        if arm == "off":
            continue
        miss = [r for r in rows if r["label"] != "standalone" and r["arms"][arm]["skipped"]]
        print(f"τ={arm}: {sorted({r['id'] for r in miss}) or '없음'}")
        for r in miss[:6]:
            print(f"    {r['id']}  끔: {r['arms']['off']['text'][:46]!r}\n        켬: {r['arms'][arm]['text'][:46]!r}")

    flagged = sorted({(arm, r["id"]) for r in rows for arm in arms if arm != "off"
                      if any(w in r["arms"][arm]["text"] for w in DEFER) and not any(w in r["arms"]["off"]["text"] for w in DEFER)})
    print(f"\n켠 설정에서만 보류·사과 표현이 나온 질문: {flagged or '없음'}")
    print("※ 답변은 실행마다 조금 다를 수 있다. 위 표시는 힌트일 뿐이다.")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
