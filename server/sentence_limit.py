"""답변 문장 수 상한 — 프롬프트(v1.3, 2~3문장)를 넘겨도 음성 답변이 길어지지 않게 하는 안전장치.

문장 끝(. ? ! 다음에 공백/줄바꿈)을 셀 때 "1.75", "4.5"처럼 숫자 사이 마침표는
뒤에 공백이 없으므로 문장 끝으로 세지 않는다. 상한에 닿으면 스트리밍을 끊어
나머지 생성도 멈춘다(비용·지연 절약). MAX_SENTENCES=0 이면 끈다.
"""
from __future__ import annotations

import os
import re

MAX_SENTENCES = int(os.environ.get("MAX_SENTENCES", "3"))

_SENTENCE_END = re.compile(r"[.?!。](?=\s)")


def limit_text(text: str, n: int = MAX_SENTENCES) -> str:
    if n <= 0:
        return text
    ends = list(_SENTENCE_END.finditer(text + " "))
    if len(ends) <= n:
        return text
    return text[: ends[n - 1].end()].strip()


def limit_stream(pieces, n: int = MAX_SENTENCES):
    """토큰 조각을 흘려보내다가 n번째 문장이 끝나면 멈춘다."""
    if n <= 0:
        yield from pieces
        return
    buffer = ""
    for piece in pieces:
        buffer += piece
        ends = list(_SENTENCE_END.finditer(buffer))
        if len(ends) >= n:
            cut = ends[n - 1].end()
            emitted = len(buffer) - len(piece)
            if cut > emitted:
                yield buffer[emitted:cut]
            close = getattr(pieces, "close", None)
            if close:
                close()  # 남은 생성 중단
            return
        yield piece
