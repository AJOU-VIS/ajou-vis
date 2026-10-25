"""스모크 테스트 결과 두 개를 비교해 전후 비교표(markdown) 생성
프롬프트 버전 간(v1.2.1 → v1.3), 모델 간(opus-5 vs sonnet-5-5) 비교에 사용

실행 (저장소 루트, cmd):
  server\\.venv\\Scripts\\python eval\\smoke\\compare.py <이전>.json <이후>.json

결과: eval/smoke/results/compare_<이전 시각>_vs_<이후 시각>.md
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

LLM_PATHS = {"llm", "rewrite", "no_search", "smalltalk"}


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["stem"] = Path(path).stem
    return data


def label(data: dict) -> str:
    m = data["meta"]
    return f"{m['prompt_version']} · {m['model']}"


def stats(data: dict) -> dict:
    rs = data["results"]
    gen = [r for r in rs if r["path"] in LLM_PATHS and r["answer"]]
    ko = [len(r["answer"]) for r in gen if r.get("answer_lang", r["lang"]) == "ko"]
    en = [len(r["answer"].split()) for r in gen if r.get("answer_lang", r["lang"]) == "en"]
    return {
        "pass": sum(r["auto_pass"] for r in rs),
        "n": len(rs),
        "issues": sum(len(r["issues"]) for r in rs),
        "long": sum(any("음성 기준 긺" in w for w in r["warnings"]) for r in rs),
        "cut": sum(any("잘림" in i for i in r["issues"]) for r in rs),
        "ko_chars": statistics.mean(ko) if ko else 0,
        "en_words": statistics.mean(en) if en else 0,
        # 첫 케이스에 모델 로딩이 섞인 실행도 있어 평균 대신 중앙값
        "latency": statistics.median(r["seconds"] for r in gen) if gen else 0,
        "out_tokens": data["meta"]["tokens_out"],
        "usd": data["meta"]["usd"],
    }


def fmt_delta(before: float, after: float, digits: int = 0, lower_is_better: bool = True) -> str:
    diff = after - before
    if abs(diff) < 10 ** -digits / 2:
        return "—"
    better = (diff < 0) == lower_is_better
    return f"{diff:+.{digits}f} {'✅' if better else '⚠️'}"


def length_of(r: dict) -> str:
    if not r["answer"]:
        return "-"
    if r.get("answer_lang", r["lang"]) == "en":
        return f"{len(r['answer'].split())}단어"
    return f"{len(r['answer'])}자"


def auto_of(r: dict) -> str:
    return "통과" if r["auto_pass"] else f"실패 {len(r['issues'])}"


def main():
    ap = argparse.ArgumentParser(description="스모크 테스트 결과 전후 비교")
    ap.add_argument("before")
    ap.add_argument("after")
    args = ap.parse_args()

    a, b = load(args.before), load(args.after)
    sa, sb = stats(a), stats(b)
    by_id = {r["id"]: r for r in b["results"]}

    lines = [
        f"# 스모크 테스트 비교 — {label(a)} → {label(b)}",
        "",
        f"- 이전: `{a['stem']}` ({a['meta']['started']}, 코드 {a['meta']['git']})",
        f"- 이후: `{b['stem']}` ({b['meta']['started']}, 코드 {b['meta']['git']})",
        "- 같은 케이스(`eval/smoke/cases.json`)·같은 검색 DB·같은 게이트 임계값. LLM 답변은 실행마다 조금씩 달라질 수 있다.",
        "",
        "## 지표",
        "",
        "| 지표 | 이전 | 이후 | 변화 |",
        "|---|---|---|---|",
        f"| 자동 점검 통과 | {sa['pass']}/{sa['n']} | {sb['pass']}/{sb['n']} | {fmt_delta(sa['pass'], sb['pass'], lower_is_better=False)} |",
        f"| 실패 항목 수 | {sa['issues']} | {sb['issues']} | {fmt_delta(sa['issues'], sb['issues'])} |",
        f"| 답변 잘림 | {sa['cut']} | {sb['cut']} | {fmt_delta(sa['cut'], sb['cut'])} |",
        f"| 음성 길이 초과 (150자 / 50단어) | {sa['long']} | {sb['long']} | {fmt_delta(sa['long'], sb['long'])} |",
        f"| 평균 길이 — 한국어 | {sa['ko_chars']:.0f}자 | {sb['ko_chars']:.0f}자 | {fmt_delta(sa['ko_chars'], sb['ko_chars'])} |",
        f"| 평균 길이 — 영어 | {sa['en_words']:.0f}단어 | {sb['en_words']:.0f}단어 | {fmt_delta(sa['en_words'], sb['en_words'])} |",
        f"| 응답 시간 중앙값 (LLM 답변) | {sa['latency']:.1f}s | {sb['latency']:.1f}s | {fmt_delta(sa['latency'], sb['latency'], 1)} |",
        f"| 출력 토큰 합계 | {sa['out_tokens']:,} | {sb['out_tokens']:,} | {fmt_delta(sa['out_tokens'], sb['out_tokens'])} |",
    ]
    if sa["usd"] is not None and sb["usd"] is not None:
        lines.append(f"| 실행 비용 (추정) | ${sa['usd']:.3f} | ${sb['usd']:.3f} | {fmt_delta(sa['usd'], sb['usd'], 3)} |")

    zones = []
    for r in a["results"]:
        if r["zone"] not in zones:
            zones.append(r["zone"])
    lines += ["", "## 구간별 자동 점검 통과", "", "| 구간 | 이전 | 이후 |", "|---|---|---|"]
    for z in zones:
        ra = [r for r in a["results"] if r["zone"] == z]
        rb = [r for r in b["results"] if r["zone"] == z]
        lines.append(f"| {z} | {sum(r['auto_pass'] for r in ra)}/{len(ra)} | {sum(r['auto_pass'] for r in rb)}/{len(rb)} |")

    lines += [
        "", "## 케이스별", "",
        "| ID | 구간 | 이전 | 이후 | 길이 | 이후 남은 문제 |",
        "|---|---|---|---|---|---|",
    ]
    for ra in a["results"]:
        rb = by_id.get(ra["id"])
        if rb is None:
            continue
        left = "; ".join(rb["issues"]) or "-"
        lines.append(
            f"| {ra['id']} | {ra['zone']} | {auto_of(ra)} | {auto_of(rb)} "
            f"| {length_of(ra)} → {length_of(rb)} | {left.replace('|', '/')} |"
        )

    lines += ["", "## 답변 전후", ""]
    for ra in a["results"]:
        rb = by_id.get(ra["id"])
        if rb is None or (not ra["answer"] and not rb["answer"]):
            continue
        lines += [
            f"### {ra['id']} · {ra['zone']} — {ra['question']}",
            "",
            f"- 기대: {rb.get('expected') or ra.get('expected')}",
            "",
            f"**이전** ({auto_of(ra)}, {length_of(ra)})",
            "",
            f"> {ra['answer'] or '(답변 없음)'}".replace("\n", " "),
            "",
            f"**이후** ({auto_of(rb)}, {length_of(rb)})",
            "",
            f"> {rb['answer'] or '(답변 없음)'}".replace("\n", " "),
            "",
        ]
        for i in rb["issues"]:
            lines.append(f"- ❌ {i}")
        lines.append("")

    ta = a["meta"]["started"].replace("-", "").replace(" ", "-").replace(":", "")
    tb = b["meta"]["started"].replace("-", "").replace(" ", "-").replace(":", "")
    out = Path(args.after).parent / f"compare_{ta}_vs_{tb}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"자동 점검 {sa['pass']}/{sa['n']} → {sb['pass']}/{sb['n']}, "
          f"한국어 평균 {sa['ko_chars']:.0f}자 → {sb['ko_chars']:.0f}자, "
          f"영어 평균 {sa['en_words']:.0f}단어 → {sb['en_words']:.0f}단어")
    print(f"결과: {out}")


if __name__ == "__main__":
    main()
