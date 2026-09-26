#!/usr/bin/env python3
"""파이프라인 구간별 지연 측정 v1 — speech-to-speech 실행 로그 파싱.

파이프라인 로그(run_local_ko.sh가 남기는 run_local.log 등)에서 턴마다
  VAD 발화 종료 → STT 완료 → LLM 응답 준비 → TTS 첫 오디오(TTFA)
타임스탬프를 뽑아 구간별 지연을 표와 CSV로 만든다.

사용법:
    python bench/latency_report.py <로그파일> [--csv 결과.csv]

한계(v1): LLM '첫 토큰' 시점은 로그에 없어서 LLM 출력 처리 완료 로그를 대신 쓴다.
정확한 첫 토큰 시점은 파이프라인 계측(v2)에서 추가 예정.
"""
import argparse
import csv
import re
import sys
from datetime import datetime

TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
PATTERNS = {
    # 발화 종료(최종 revision이 기준이 되도록 턴마다 마지막 것을 사용)
    "vad_end": re.compile(TS + r".*vad_handler.*Speech soft-ended.*turn=(\S+)"),
    "stt_done": re.compile(TS + r".*transcription_notifier.*Transcription completed \(language=(\S+)\): chars=(\d+)"),
    "llm_done": re.compile(TS + r".*language_model - INFO - Tools:"),
    "tts_ttfa": re.compile(TS + r".*Qwen3-TTS TTFA: ([\d.]+)s"),
}


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S,%f")


def parse(path):
    turns, cur = [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = PATTERNS["vad_end"].search(line)
        if m:
            t, turn_id = ts(m.group(1)), m.group(2)
            # 같은 턴의 revision 갱신이면 시각만 갱신, 새 턴이면 이전 턴을 닫는다
            if cur and cur["turn"] == turn_id and cur["stt_done"] is None:
                cur["vad_end"] = t
            else:
                if cur:
                    turns.append(cur)
                cur = {"turn": turn_id, "vad_end": t, "stt_done": None,
                       "lang": None, "chars": None, "llm_done": None,
                       "tts_start": None, "ttfa": None}
            continue
        if cur is None:
            continue
        m = PATTERNS["stt_done"].search(line)
        if m and cur["stt_done"] is None:
            cur["stt_done"], cur["lang"], cur["chars"] = ts(m.group(1)), m.group(2), int(m.group(3))
            continue
        m = PATTERNS["llm_done"].search(line)
        if m and cur["stt_done"] is not None and cur["llm_done"] is None:
            cur["llm_done"] = ts(m.group(1))
            continue
        m = PATTERNS["tts_ttfa"].search(line)
        if m and cur["llm_done"] is not None and cur["tts_start"] is None:
            cur["tts_start"], cur["ttfa"] = ts(m.group(1)), float(m.group(2))
    if cur:
        turns.append(cur)
    return [t for t in turns if t["stt_done"] is not None]


def seconds(a, b):
    return round((b - a).total_seconds(), 3) if a and b else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--csv", default=None, help="구간별 지연을 CSV로 저장")
    args = ap.parse_args()

    turns = parse(args.logfile)
    if not turns:
        sys.exit("파싱된 턴이 없습니다. 로그 파일과 포맷을 확인하세요.")

    rows = []
    for t in turns:
        stt = seconds(t["vad_end"], t["stt_done"])
        llm = seconds(t["stt_done"], t["llm_done"])
        tts_queue = seconds(t["llm_done"], t["tts_start"])
        total = None
        if t["tts_start"] and t["ttfa"] is not None:
            total = round(seconds(t["vad_end"], t["tts_start"]) + t["ttfa"], 3)
        rows.append({
            "턴": t["turn"], "언어": t["lang"], "질문 길이(자)": t["chars"],
            "STT(s)": stt, "LLM(s)": llm, "TTS 대기(s)": tts_queue,
            "TTS TTFA(s)": t["ttfa"],
            "발화 종료→첫 오디오(s)": total,
        })

    headers = list(rows[0].keys())
    widths = [max(len(str(h)), *(len(str(r[h])) for r in rows)) for h in headers]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for r in rows:
        print("  ".join(str(r[h]).ljust(w) for h, w in zip(headers, widths)))

    valid = [r["발화 종료→첫 오디오(s)"] for r in rows if r["발화 종료→첫 오디오(s)"]]
    if valid:
        print(f"\n턴 {len(valid)}개 평균 체감 지연(발화 종료→첫 오디오): {sum(valid)/len(valid):.2f}s")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            w.writerows(rows)
        print(f"CSV 저장: {args.csv}")


if __name__ == "__main__":
    main()
