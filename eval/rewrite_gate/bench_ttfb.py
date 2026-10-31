"""RAG 서버에 시험 세트를 직접 보내 '요청 → 첫 글자' 시간을 재서 관문 끔/켬을 비교한다 (음성 필요 없음).

서버는 요청 본문의 rewrite_gate(true/false) 필드로 관문을 요청마다 켜고 끌 수 있으므로,
같은 서버 인스턴스에 두 방식을 번갈아 보내 네트워크·캐시 영향을 줄인다.
Claude API를 실제로 호출하므로 비용이 든다 (40개 × 2방식 ≈ 약 $0.2 안팎, 모델에 따라 다름).

실행 (서버와 같은 기기에서 — Colab이면 새 코드 셀에서 !python …):
  python eval/rewrite_gate/bench_ttfb.py --url http://127.0.0.1:8100/v1/chat/completions
  python eval/rewrite_gate/bench_ttfb.py --url ... --repeat 2 --only standalone --out bench_result.json
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


def ask(url: str, messages: list[dict], gate: bool, timeout: float = 60.0):
    """(첫 글자까지 초, 전체 초, 답변 앞부분)을 돌려준다."""
    body = json.dumps({"model": "ajou-vis", "stream": True, "messages": messages, "rewrite_gate": gate}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    text = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                delta = json.loads(payload)["choices"][0]["delta"].get("content") or ""
            except (KeyError, IndexError, ValueError):
                continue
            if delta:
                if first is None:
                    first = time.perf_counter() - t0
                text.append(delta)
    total = time.perf_counter() - t0
    return first, total, "".join(text)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def f2(x):
    return "-" if x is None else f"{x:.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8100/v1/chat/completions")
    ap.add_argument("--cases", default=str(Path(__file__).with_name("cases.json")))
    ap.add_argument("--repeat", type=int, default=1, help="각 질문을 몇 번 보낼지")
    ap.add_argument("--only", help="label만 (followup, format, standalone)")
    ap.add_argument("--warmup", type=int, default=2, help="결과에서 버릴 앞쪽 요청 수(모델·연결 예열)")
    ap.add_argument("--out", help="결과 json 저장 경로")
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if c["label"] == args.only]

    # 예열 (결과에서 제외): 첫 요청은 모델·연결 때문에 느리다
    for c in cases[:args.warmup]:
        ask(args.url, c["messages"], False)

    rows = []
    k = 0
    for rep in range(args.repeat):
        for c in cases:
            order = (False, True) if k % 2 == 0 else (True, False)   # 순서를 번갈아 편향을 줄인다
            k += 1
            res = {}
            for gate in order:
                try:
                    res[gate] = ask(args.url, c["messages"], gate)
                except Exception as e:  # 한 건 실패가 전체를 멈추지 않게
                    res[gate] = (None, None, f"(오류: {type(e).__name__})")
            rows.append({"id": c["id"], "label": c["label"], "rep": rep,
                         "off": {"first": res[False][0], "total": res[False][1], "text": res[False][2][:80]},
                         "on": {"first": res[True][0], "total": res[True][1], "text": res[True][2][:80]}})
            print(f"  {c['id']} {c['label']:<10} 끔 {f2(res[False][0])}s · 켬 {f2(res[True][0])}s")

    print("\n=== 요청 → 첫 글자 (초) ===")
    print("종류           끔(중앙)  켬(중앙)  절감   n")
    for lab in ("followup", "format", "standalone", "전체"):
        sub = rows if lab == "전체" else [r for r in rows if r["label"] == lab]
        if not sub:
            continue
        a, b = med([r["off"]["first"] for r in sub]), med([r["on"]["first"] for r in sub])
        print(f"{lab:<12}  {f2(a):>7}  {f2(b):>7}  {f2(a - b) if a and b else '-':>5}  {len(sub)}")

    # 켠 쪽에서만 '답을 못 한 것 같은' 답변이 나온 경우 (품질 퇴행 힌트 — 최종 판단은 사람이)
    flagged = [r for r in rows if any(w in r["on"]["text"] for w in DEFER) and not any(w in r["off"]["text"] for w in DEFER)]
    print(f"\n켠 쪽에서만 보류·사과 표현이 나온 질문: {[r['id'] for r in flagged] or '없음'}")
    print("※ 답변은 실행마다 조금 다를 수 있다. 위 표시는 힌트일 뿐이며, 해당 질문은 답변 본문(결과 json)을 직접 확인한다.")
    print('서버 로그에서 재작성이 생략된 요청 수: grep -c "재작성 생략" <서버 로그 파일>')
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
