#!/usr/bin/env python3
"""1단계: LLM으로 학습형 게이트용 대화 샘플을 만든다 (Claude API 호출 — 비용 발생).

코퍼스의 서로 다른 문서에서 주제 A, B를 짝지어 한 번에 (이전 대화 + 주제 A 꼬리질문 3개 + 주제 B 독립 질문 3개)를 만든다.
꼬리질문은 지시어·접속어 없이 앞 맥락이 있어야만 뜻이 통하는 '어려운' 것으로 요청한다.
호출은 이어서 할 수 있다: 중간에 끊겨도 같은 명령을 다시 실행하면 이미 만든 호출은 건너뛴다.

실행 (저장소 루트, 서버 가상환경에서):
  server/.venv/bin/python eval/gate_learn/gen_data.py --dry-run                 # 프롬프트만 보고 끝 (과금 없음)
  server/.venv/bin/python eval/gate_learn/gen_data.py --n-calls 120             # 실제 생성 (약 $1 안팎, 모델에 따라 다름)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_lib as L  # noqa: E402


def generate(pairs, chat, out_path: Path, sleep: float = 0.0, log=print):
    """pairs의 각 (A, B)에 대해 chat(system, user, max_tokens)을 불러 샘플을 out_path에 이어 쓴다. (성공 수, 실패 수) 반환."""
    done = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                done.add(json.loads(line)["call"])
            except (ValueError, KeyError):
                pass
    ok = bad = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        for i, (a, b) in enumerate(pairs):
            if i in done:
                continue
            system, user = L.build_prompt(a, b)
            gen = None
            for attempt in range(3):
                try:
                    gen = L.parse_generation(chat(system, user, 1800))
                except Exception as e:  # 한 호출의 실패가 전체를 멈추지 않게
                    log("  호출 오류(%s) — 재시도 %d/3" % (type(e).__name__, attempt + 1))
                    time.sleep(2 + 2 * attempt)
                    gen = None
                    continue
                if gen:
                    break
            if not gen:
                bad += 1
                continue
            for s in L.to_samples(i, a, b, gen):
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
            f.flush()
            ok += 1
            if (ok + bad) % 10 == 0:
                log("  진행: 성공 %d · 실패 %d / 요청 %d" % (ok, bad, len(pairs) - len(done)))
            if sleep:
                time.sleep(sleep)
    return ok, bad


def main():
    ap = argparse.ArgumentParser(description="학습형 게이트용 대화 샘플 생성")
    ap.add_argument("--n-calls", type=int, default=120, help="LLM 호출 수 (호출당 샘플 최대 6개)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--model", default="claude-haiku-4-5", help="생성에 쓸 모델")
    ap.add_argument("--out", default=str(HERE / "data" / "samples.jsonl"))
    ap.add_argument("--sleep", type=float, default=0.2, help="호출 사이 대기(초)")
    ap.add_argument("--dry-run", action="store_true", help="첫 프롬프트만 출력하고 끝낸다")
    args = ap.parse_args()

    units = L.load_units()
    pairs = L.make_pairs(units, args.n_calls, args.seed)
    print("코퍼스 단위 %d개 → 주제 짝 %d개 (요청 %d)" % (len(units), len(pairs), args.n_calls))
    if not pairs:
        raise SystemExit("주제 짝을 만들지 못했습니다 (corpus/raw를 확인하세요)")
    system, user = L.build_prompt(*pairs[0])
    approx_tok = (len(system) + len(user)) / 2.2
    print("프롬프트 약 %d토큰 × %d호출 = 입력 약 %.2fM토큰 (출력은 호출당 약 1K토큰으로 추정)" % (approx_tok, len(pairs), approx_tok * len(pairs) / 1e6))
    if args.dry_run:
        print("\n=== 첫 번째 프롬프트 ===\n" + user)
        return

    os.environ["LLM_MODEL"] = args.model            # llm 모듈이 import 시점에 읽는다 (.env 값보다 우선하게 먼저 설정)
    try:
        from dotenv import load_dotenv
        load_dotenv(L.ROOT / "server" / ".env", override=False)
    except ImportError:
        pass
    import llm  # noqa: E402  (server/llm.py)

    t0 = time.time()
    ok, bad = generate(pairs, llm.chat, Path(args.out), sleep=args.sleep)
    rows = [json.loads(l) for l in open(args.out, encoding="utf-8") if l.strip()]
    print("\n완료: 성공 %d · 실패 %d · 파일의 샘플 총 %d개 (%.0f초) → %s" % (ok, bad, len(rows), time.time() - t0, args.out))
    import re
    import statistics
    for t in ("followup", "standalone"):
        ls = sorted(len(re.sub(r"\s", "", r["utterance"])) for r in rows if r["type"] == t)
        if ls:
            print("  %-10s 발화 길이(공백 제외) 중앙값 %d · 25~75%% %d~%d · 범위 %d~%d" % (
                t, statistics.median(ls), ls[len(ls) // 4], ls[3 * len(ls) // 4], ls[0], ls[-1]))
    print("  → 두 종류의 길이 분포가 많이 겹쳐야 한다(이전 데이터: 꼬리질문 중앙값 12 대 독립 질문 19).")


if __name__ == "__main__":
    main()
