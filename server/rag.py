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
    """ChromaDB 미구축 시 자리표시자 — 항상 빈 결과."""

    def search(self, question: str, top_k: int = 5) -> list[SearchHit]:
        return []


class ChromaRetriever:
    """corpus/chroma_db 규정 벡터 저장소 검색 (embed_corpus.py가 구축, BGE-M3).

    임베딩 모델(~2GB)은 첫 검색 때 지연 로드한다 — 서버 기동과 테스트를
    느리게 만들지 않기 위해서. 로드 후에는 메모리에 유지된다.
    """

    COLLECTION = "ajou_regulations"
    MODEL_NAME = "BAAI/bge-m3"  # embed_corpus.py와 반드시 동일해야 함

    def __init__(self, db_dir):
        self._db_dir = str(db_dir)
        self._model = None
        self._collection = None

    def _ensure_loaded(self):
        if self._model is None:
            import chromadb
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.MODEL_NAME)
            client = chromadb.PersistentClient(path=self._db_dir)
            self._collection = client.get_collection(self.COLLECTION)

    def search(self, question: str, top_k: int = 5) -> list[SearchHit]:
        self._ensure_loaded()
        embedding = self._model.encode([question], normalize_embeddings=True)[0].tolist()
        res = self._collection.query(query_embeddings=[embedding], n_results=top_k)

        hits = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            # 정규화 벡터의 제곱 L2 거리 → 코사인 유사도 (cos = 1 - d/2).
            # gate.py의 임계값 판단이 이 점수를 사용한다 (계약 ①·②).
            score = max(0.0, 1.0 - dist / 2)
            hits.append(SearchHit(
                source_name=meta["rule_name"],
                article=f"{meta['article_no']}({meta['article_title']})",
                text=doc,
                score=score,
            ))
        return hits


def format_context(hits: list[SearchHit]) -> str:
    """계약 ② 형식으로 직렬화: [출처: 문서명 | 조항/URL] 본문 (점수: 0.00).
    구분자(|)는 prompts/system_ko·en.md, user_turn.md와 반드시 같아야 한다."""
    return "\n".join(
        f"[출처: {h.source_name} | {h.article}] {h.text} (점수: {h.score:.2f})"
        for h in hits
    )
