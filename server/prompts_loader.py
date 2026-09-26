"""prompts/*.md 로드와 자리표시자 채움 (프롬프트 계약 ③·④).

프롬프트 파일이 곧 스펙이므로 여기서 가공하지 않는다 — 주석 블록 제거와
자리표시자 치환만 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


def _load(name: str) -> str:
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    return _COMMENT.sub("", text, count=1).strip()


def system_prompt(lang: str) -> str:
    return _load("system_en.md" if lang == "en" else "system_ko.md")


def user_turn(history: str, lang: str, question: str, context: str) -> str:
    return (
        _load("user_turn.md")
        .replace("{{RECENT_HISTORY}}", history)
        .replace("{{LANG}}", lang)
        .replace("{{CURRENT_QUESTION}}", question)
        .replace("{{RETRIEVED_CONTEXT}}", context)
    )


def rewrite_prompt(history: str, utterance: str) -> str:
    return (
        _load("rewrite.md")
        .replace("{{RECENT_HISTORY}}", history)
        .replace("{{CURRENT_UTTERANCE}}", utterance)
    )


def detect_lang(text: str) -> str:
    """v1: 한글 포함 여부로 ko/en 판별. 파이프라인 언어코드 전달 경로 확정 후 교체."""
    return "ko" if re.search(r"[가-힣]", text) else "en"
