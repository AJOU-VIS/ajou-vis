"""prompts/*.md 로드와 자리표시자 채움 (프롬프트 계약 ③·④).

프롬프트 파일이 곧 스펙이므로 여기서 가공하지 않는다 — 주석 블록 제거,
시스템 프롬프트 뒤 페르소나 결합, 자리표시자 치환만 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)
# persona_ko.md의 목소리(TTS) 블록 — TTS용이라 LLM에는 보내지 않는다
_TTS_BLOCK = re.compile(r"<!--\s*TTS:BEGIN\s*-->.*?<!--\s*TTS:END\s*-->\s*", re.DOTALL)


def _load(name: str) -> str:
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    return _COMMENT.sub("", text, count=1).strip()


def persona(lang: str) -> str:
    """치토 페르소나 본문 (목소리 블록 제외)."""
    return _TTS_BLOCK.sub("", _load("persona_en.md" if lang == "en" else "persona_ko.md")).strip()


def system_prompt(lang: str) -> str:
    """규칙(system_*.md) 뒤에 페르소나(persona_*.md)를 붙인다 — 규칙이 앞에 오고 충돌 시 우선한다.

    페르소나는 <persona> 태그로 감싼다. 마크다운 제목으로 이어 붙였을 때 모델이 그 제목을
    답변 끝에 따라 쓴 사례가 있었다 (Haiku, "# Persona: Chito").
    """
    rules = _load("system_en.md" if lang == "en" else "system_ko.md")
    return f"{rules}\n\n<persona>\n{persona(lang)}\n</persona>"


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
