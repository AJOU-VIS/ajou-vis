"""
AJOU-VIS 규정 코퍼스 임베딩 스크립트
=================================================
크롤러(rules_crawler.py)가 만든 규정 조항 JSON들을 읽어서
BGE-M3 임베딩 모델로 벡터화하고 ChromaDB에 저장한다.

디렉토리 구조
------------------------------------------
corpus/
  raw/                 <- 크롤러 결과 JSON (규정별 파일)
  chroma_db/           <- 이 스크립트가 벡터를 저장하는 곳 (자동 생성, git 추적 제외)
  scripts/
    rules_crawler.py   <- 규정 조항 크롤러
    embed_corpus.py    <- 바로 이 파일

실행 방법
---------
1. corpus/raw/ 에 규정 조항 JSON이 있는지 확인
2. pip install sentence-transformers langchain-text-splitters chromadb
3. python corpus/scripts/embed_corpus.py
4. 끝나면 대화형 검색 테스트가 실행됨 ("질문 입력:" 프롬프트에 질의 입력)

검증 현황
----
학칙·장학금 지급규칙·외국인학생 지원규칙 3개(총 111개 조항, 179개 청크)로
로컬에서 실행 및 검색 테스트 완료. "휴학 신청은 어떻게 해?" 등의 질의로
관련 조항이 상위에 정확히 검색되는 것을 확인함.
검색 결과에 "근거 없음" 판단은 포함하지 않음 — 이 스크립트는 후보를
찾아주는 역할까지이며, 근거 유무 판단은 이후 프롬프트/LLM 단계에서 처리.
"""

import json
from pathlib import Path

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

# ── 설정 ──────────────────────────────────────────────────────────
RAW_DIR = Path(__file__).parent.parent / "raw"
DB_DIR = Path(__file__).parent.parent / "chroma_db"
COLLECTION_NAME = "ajou_regulations"
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"

# 조항이 이 길이(글자수)를 넘으면 RAG 기본값(300~500자, overlap 50~100)에
# 맞춰 추가로 쪼갠다. 짧은 조항은 그대로 하나의 청크로 둔다.
LONG_ARTICLE_THRESHOLD = 500
SPLIT_CHUNK_SIZE = 450
SPLIT_CHUNK_OVERLAP = 80


def load_articles() -> list[dict]:
    """corpus/raw/ 안의 모든 규정 JSON을 읽어서 조항 리스트로 합친다.
    각 조항에 소속 규정명·URL 등 메타데이터를 같이 붙인다."""
    all_articles = []
    json_files = sorted(RAW_DIR.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(
            f"{RAW_DIR} 에 JSON 파일이 없습니다. "
            f"rules_crawler.py의 output/*.json을 이 폴더로 복사했는지 확인하세요."
        )

    for path in json_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        for article in data.get("articles", []):
            all_articles.append({
                "rule_name": data["rule_name"],
                "rule_id": data["rule_id"],
                "url": data["url"],
                "effective_date": data.get("effective_date"),
                "article_no": article["article_no"],
                "article_title": article["article_title"],
                "text": article["text"],
            })

    print(f"[로드 완료] 규정 {len(json_files)}건, 조항 {len(all_articles)}개")
    return all_articles


def build_chunks(articles: list[dict]) -> tuple[list[str], list[dict], list[str]]:
    """조항들을 ChromaDB에 넣을 (문서 텍스트, 메타데이터, 고유 id) 리스트로 변환.
    너무 긴 조항은 여러 청크로 쪼개되, 어느 조항에서 나왔는지는
    메타데이터(article_no 등)로 계속 추적 가능하게 유지한다."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=SPLIT_CHUNK_SIZE,
        chunk_overlap=SPLIT_CHUNK_OVERLAP,
        separators=["\n", "。", ". ", " "],
    )

    documents, metadatas, ids = [], [], []
    for article in articles:
        text = article["text"]
        base_id = f"{article['rule_id']}_{article['article_no']}"

        if len(text) <= LONG_ARTICLE_THRESHOLD:
            pieces = [text]
        else:
            pieces = splitter.split_text(text)

        for i, piece in enumerate(pieces):
            documents.append(piece)
            metadatas.append({
                "rule_name": article["rule_name"],
                "rule_id": article["rule_id"],
                "url": article["url"],
                "effective_date": article["effective_date"] or "",
                "article_no": article["article_no"],
                "article_title": article["article_title"],
                "chunk_index": i,
            })
            ids.append(f"{base_id}_{i}")

    print(f"[청크 생성 완료] 총 {len(documents)}개 청크 "
          f"(조항 {len(articles)}개 중 {SPLIT_CHUNK_SIZE}자 넘는 건 분할됨)")
    return documents, metadatas, ids


def embed_and_store(documents: list[str], metadatas: list[dict], ids: list[str]) -> None:
    """BGE-M3로 임베딩하고 ChromaDB에 저장."""
    print(f"[임베딩 모델 로드 중] {EMBEDDING_MODEL_NAME} (처음 실행 시 다운로드로 시간이 걸림)")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    print("[임베딩 계산 중] ...")
    embeddings = model.encode(documents, show_progress_bar=True, normalize_embeddings=True)

    DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_DIR))

    # 재실행 시 중복 저장 방지를 위해 기존 컬렉션이 있으면 지우고 새로 만든다.
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    # ChromaDB는 한 번에 너무 많은 항목을 넣으면 에러가 날 수 있어 배치로 나눠 추가.
    batch_size = 200
    for start in range(0, len(documents), batch_size):
        end = start + batch_size
        collection.add(
            documents=documents[start:end],
            embeddings=embeddings[start:end].tolist(),
            metadatas=metadatas[start:end],
            ids=ids[start:end],
        )

    print(f"[저장 완료] {DB_DIR} 에 컬렉션 '{COLLECTION_NAME}' 저장됨 "
          f"(총 {collection.count()}개 청크)")


def search_demo(query: str, top_k: int = 3) -> None:
    """같은 임베딩 모델로 질문을 벡터화해서 ChromaDB에서 검색해보는 데모."""
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    query_embedding = model.encode([query], normalize_embeddings=True)[0].tolist()
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)

    print(f"\n질문: {query}")
    for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
        print(f"\n  [{i + 1}] {meta['rule_name']} {meta['article_no']}({meta['article_title']})")
        print(f"      {doc[:150]}{'...' if len(doc) > 150 else ''}")


def interactive_search_loop() -> None:
    print("\n" + "=" * 60)
    print("검색 테스트 (빈 줄 입력하면 종료)")
    print("=" * 60)
    while True:
        query = input("\n질문 입력: ").strip()
        if not query:
            break
        search_demo(query)


def main():
    articles = load_articles()
    documents, metadatas, ids = build_chunks(articles)
    embed_and_store(documents, metadatas, ids)
    interactive_search_loop()


if __name__ == "__main__":
    main()
