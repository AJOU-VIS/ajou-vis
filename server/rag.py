"""RAG 검색 인터페이스 (프롬프트 계약 ②).

태연님 연결 지점: Retriever.search()를 ChromaDB + BGE-M3로 구현해서
app.py의 retriever를 교체하면 된다. 그 전까지 StubRetriever가 빈 결과를
반환하므로 게이트가 모든 질문을 보류 응답으로 처리한다(무근거 답변 원천 차단).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchHit:
    source_name: str  # 소리내 읽기 자연스러운 문서명 (예: "아주대학교 학칙")
    article: str      # 조항 또는 URL (예: "제31조")
    text: str         # 본문 청크
    score: float      # 유사도 점수 (게이트 임계값 판단에 사용)


class Retriever(Protocol):
    def search(self, question: str, top_k: int = 5) -> list[SearchHit]: ...


class StubRetriever:
    """ChromaDB 연결 전 자리표시자 — 항상 빈 결과."""

    def search(self, question: str, top_k: int = 5) -> list[SearchHit]:
        return []


def format_context(hits: list[SearchHit]) -> str:
    """계약 ② 형식으로 직렬화. 구분자(쉼표)는 현행 프롬프트 파일 기준 —
    docs/prompt_design.md의 파이프(|)와 불일치가 있어 확정 후 통일 예정."""
    return "\n".join(
        f"[출처: {h.source_name}, {h.article}] {h.text} (점수: {h.score:.2f})"
        for h in hits
    )
