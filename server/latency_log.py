"""RAG 서버 요청 한 건의 구간별 시간을 터미널에 한 줄로 남긴다 (지연 분해용).

출력 예:
  [timing] 경로=chroma | 재작성 0.00 | 검색·게이트 0.21 | Claude 첫 토큰 0.93 | 요청→첫 조각 1.16 (초)

음성 파이프라인의 latency_trace(llm_first_delta)에 들어 있는 시간이 이 서버 안에서 어디에 쓰이는지 쪼개 준다.
순서: 요청 수신 → (재작성) → (검색·게이트) → Claude 호출 → 첫 토큰 → 첫 문장 조각이 응답으로 나감.
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Iterator


def start() -> dict[str, Any]:
    return {"t0": time.perf_counter(), "path": "chroma"}


def mark(t: dict[str, Any] | None, key: str) -> None:
    if t is not None:
        t[key] = time.perf_counter()


def mark_first(it: Iterable[Any], t: dict[str, Any] | None, key: str, log_it: bool = False) -> Iterator[Any]:
    """이터레이터를 그대로 통과시키되, 첫 항목이 나오는 시각을 t[key]에 기록한다."""
    first = True
    for x in it:
        if first:
            first = False
            if t is not None:
                t[key] = time.perf_counter()
                if log_it:
                    log(t)
        yield x


def _d(t: dict[str, Any], a: str, b: str) -> str:
    return f"{t[b] - t[a]:.2f}" if a in t and b in t else "-"


def _rw(t: dict[str, Any]) -> str:
    """재작성 시간. 관문이 켜져 있으면 생략/호출 이유를 같이 적는다."""
    d = _d(t, 't0', 't_rewrite')
    if t.get('rw_skip'):
        return f"생략({t['rw_skip']}) {d}"
    if t.get('rw_why'):
        return f"{d}[{t['rw_why']}]"
    return d


def log(t: dict[str, Any] | None) -> None:
    if t is None:
        return
    print(
        f"[timing] 경로={t.get('path', '?')}"
        f" | 재작성 {_rw(t)}"
        f" | 검색·게이트 {_d(t, 't_rewrite', 't_search')}"
        f" | Claude 첫 토큰 {_d(t, 't_llm_start', 't_first_token')}"
        f" | 요청→첫 조각 {_d(t, 't0', 't_first_piece')} (초)",
        flush=True,
    )
