"""RAG 검색 인터페이스 (프롬프트 계약 ②).

태연님 연결 지점: Retriever.search()를 ChromaDB + BGE-M3로 구현해서
app.py의 retriever를 교체하면 된다. 그 전까지 StubRetriever가 빈 결과를
반환하므로 게이트가 모든 질문을 보류 응답으로 처리한다(무근거 답변 원천 차단).

하이브리드 검색 보완 (실측으로 확인된 문제 대응)
--------------------------------------------
"CU 어디에 있어?" 같은 질문에서, 실제로 "CU 성호관점" 청크가 DB에 있는데도
순수 임베딩 검색으로는 top 10에도 들지 못하는 걸 확인했다. BGE-M3 같은
임베딩 모델이 "CU", "GS25" 처럼 의미보다 고유명사·약어 성격이 강한 짧은
영문 토큰을 잘 포착하지 못하는 것으로 보인다. 그래서 질문에 영문 대문자
(+숫자) 토큰이 있으면, 그 글자가 본문에 그대로 포함된 청크를 직접 찾아서
(ChromaDB where_document 필터) 임베딩 검색 결과와 합치는 방식으로 보완했다.
"""
from __future__ import annotations

import re
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


# 질문에서 "CU", "GS25" 같은 영문 대문자(+숫자) 키워드를 뽑는 패턴.
# 소문자 섞인 일반 영단어까지 잡지 않도록 대문자로 시작·구성된 토큰만 보고,
# "I", "A" 같은 한 글자는 영어 문장의 일반 단어라 오탐이 많아 최소 2글자로 제한.
_KEYWORD_PATTERN = re.compile(r"[A-Z][A-Z0-9]+")

# 키워드가 본문에 글자 그대로 들어있는 청크에 더하는 점수 보너스.
# 실측: "CU 어디에 있어?"로 CU 청크를 순위 1~3위에 올려도 순수 코사인 유사도는
# 0.30~0.34에 그쳐 게이트 임계값(0.5)에서 막혔다. 질문과 의미가 아니라 글자가
# 일치한다는 건 오히려 더 강한 관련성 신호이므로, 게이트가 이를 반영하도록
# 점수를 보정한다. (0.3이면 위 실측값이 약 0.6 → 게이트 통과)
KEYWORD_SCORE_BONUS = 0.3


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

    @staticmethod
    def _score_from_distance(dist: float) -> float:
        # 정규화 벡터의 제곱 L2 거리 → 코사인 유사도 (cos = 1 - d/2).
        return max(0.0, 1.0 - dist / 2)

    def _embedding_search(self, question: str, n_results: int):
        embedding = self._model.encode([question], normalize_embeddings=True)[0].tolist()
        res = self._collection.query(query_embeddings=[embedding], n_results=n_results)
        results = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            results.append((doc, meta, self._score_from_distance(dist)))
        return results, embedding

    def _keyword_search(self, question: str, query_embedding: list[float]):
        """질문 속 영문 대문자 토큰이 본문에 그대로 포함된 청크를 직접 찾는다.
        점수는 같은 질문 임베딩과의 코사인 유사도에 KEYWORD_SCORE_BONUS를
        더한 값이다 — 글자 그대로 일치했다는 신호를 게이트(gate.py)가 반영할
        수 있게 하기 위함 (순수 코사인 유사도만으로는 임계값에 못 미침)."""
        keywords = _KEYWORD_PATTERN.findall(question)
        if not keywords:
            return []

        found = {}
        for kw in keywords:
            got = self._collection.get(
                where_document={"$contains": kw},
                include=["documents", "metadatas", "embeddings"],
            )
            for doc, meta, emb in zip(got["documents"], got["metadatas"], got["embeddings"]):
                if doc in found:
                    continue
                # 두 벡터 모두 정규화되어 있으므로 내적이 곧 코사인 유사도.
                score = float(sum(a * b for a, b in zip(query_embedding, emb)))
                # 글자 그대로 일치한 건이므로 보너스를 더한다 (상한 1.0).
                score = min(1.0, score + KEYWORD_SCORE_BONUS)
                found[doc] = (doc, meta, score)
        return list(found.values())

    def search(self, question: str, top_k: int = 5) -> list[SearchHit]:
        self._ensure_loaded()

        # 1) 일반 임베딩 검색 (후보를 top_k보다 넉넉히 가져와 키워드 매치와
        #    합칠 여유를 둔다)
        embedding_results, query_embedding = self._embedding_search(question, top_k * 3)

        # 2) 키워드(영문 대문자 토큰) 직접 매칭 — 임베딩이 놓치는 짧은
        #    고유명사(예: "CU")를 보완
        keyword_results = self._keyword_search(question, query_embedding)

        # 3) 합치기: 같은 문서가 양쪽에 다 있으면 하나만 남기고,
        #    키워드로 매칭된 문서는 맨 앞으로 끌어올린다 (질문에 그 글자가
        #    그대로 들어있다는 건 매우 강한 관련성 신호이기 때문).
        merged: dict[str, tuple] = {doc: (doc, meta, score, True)
                                     for doc, meta, score in keyword_results}
        for doc, meta, score in embedding_results:
            if doc not in merged:
                merged[doc] = (doc, meta, score, False)

        ranked = sorted(
            merged.values(),
            key=lambda r: (not r[3], -r[2]),  # 키워드 매치 우선, 그 다음 점수 내림차순
        )[:top_k]

        return [
            SearchHit(
                source_name=meta["rule_name"],
                article=f"{meta['article_no']}({meta['article_title']})",
                text=doc,
                score=score,
            )
            for doc, meta, score, _is_keyword in ranked
        ]


def format_context(hits: list[SearchHit]) -> str:
    """계약 ② 형식으로 직렬화. 구분자(쉼표)는 현행 프롬프트 파일 기준 —
    docs/prompt_design.md의 파이프(|)와 불일치가 있어 확정 후 통일 예정."""
    return "\n".join(
        f"[출처: {h.source_name}, {h.article}] {h.text} (점수: {h.score:.2f})"
        for h in hits
    )
