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


def _load_regulation_file(data: dict) -> list[dict]:
    """rules_crawler.py 결과 (학칙 등 조항 단위 규정) 하나를 공통 레코드로 변환."""
    return [
        {
            "rule_name": data["rule_name"],
            "rule_id": data["rule_id"],
            "url": data["url"],
            "effective_date": data.get("effective_date"),
            "article_no": article["article_no"],
            "article_title": article["article_title"],
            "text": article["text"],
        }
        for article in data.get("articles", [])
    ]


def _load_event_file(data: list) -> list[dict]:
    """event_calendar_crawler.py 결과(행사 일정)를 공통 레코드로 변환.
    원본은 {category, content, period} 형태 — 검색에 쓰일 자연어 문장으로 합친다."""
    records = []
    for e in data:
        text = f"{e['content']} ({e.get('category', '행사')}, 기간: {e.get('period', '미정')})"
        records.append({
            "rule_name": "아주대학교 행사 일정",
            "rule_id": "events",
            "url": "https://www.ajou.ac.kr/kr/ajou/notice-calendar.do",
            "effective_date": None,
            "article_no": None,
            "article_title": e["content"],
            "text": text,
        })
    return records


def _load_facility_file(data: list) -> list[dict]:
    """campus_facility_crawler.py 결과(캠퍼스 시설)를 공통 레코드로 변환.

    편의시설류 표는 "구분"(위치/운영시간 등)을 행으로, 업체명(CU성호관점 등)을
    칸으로 나열한 구조다. 이걸 행 그대로 한 문장으로 합치면 "CU" 같은 업체명이
    다른 업체 이름들 틈에 묻혀 검색에서 밀리는 문제가 있었다 (실측 확인됨).
    그래서 "구분" 칸이 있는 표는 업체별로 다시 묶어서, 업체 하나당 청크 하나
    (그 업체의 위치·운영시간을 다 포함)로 만든다 — 업체명이 청크의 핵심 키워드가
    되도록. "구분" 칸이 없는 표(예: 노선표처럼 행 하나가 곧 한 항목인 경우)는
    변환할 필요가 없어 원래 방식(행 전체를 한 문장으로)을 그대로 쓴다.
    """
    records = []
    for page in data:
        for table in page.get("tables", []):
            if table and "구분" in table[0]:
                # 업체별로 묶기: {업체명: ["위치: ...", "운영시간: ...", ...]}
                entities: dict[str, list[str]] = {}
                for row in table:
                    label = row.get("구분", "")
                    for key, value in row.items():
                        if key == "구분":
                            continue
                        entities.setdefault(key, []).append(
                            f"{label}: {value}" if label else str(value)
                        )
                for entity_name, parts in entities.items():
                    records.append({
                        "rule_name": f"아주대학교 {page['page_name']}",
                        "rule_id": page["page_name"],
                        "url": page["url"],
                        "effective_date": None,
                        "article_no": None,
                        "article_title": entity_name,
                        "text": f"{entity_name} ({page['page_name']}) - " + ", ".join(parts),
                    })
            else:
                # "구분" 칸이 없는 표: 기존 방식대로 행 전체를 한 문장으로
                for row in table:
                    sentence = ", ".join(f"{k}: {v}" for k, v in row.items())
                    records.append({
                        "rule_name": f"아주대학교 {page['page_name']}",
                        "rule_id": page["page_name"],
                        "url": page["url"],
                        "effective_date": None,
                        "article_no": None,
                        "article_title": page["page_name"],
                        "text": f"{page['page_name']} - {sentence}",
                    })
    return records


def load_articles() -> list[dict]:
    """corpus/raw/ 안의 모든 JSON(규정·행사·시설)을 읽어서 공통 형식으로 합친다.
    파일 내용 구조를 보고 어떤 종류인지 자동으로 판별한다 — 파일명에 의존하지 않음.
    """
    all_articles = []
    json_files = sorted(RAW_DIR.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(
            f"{RAW_DIR} 에 JSON 파일이 없습니다. "
            f"각 크롤러의 output/*.json을 이 폴더로 복사했는지 확인하세요."
        )

    counts = {"regulation": 0, "event": 0, "facility": 0}
    for path in json_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "articles" in data:
            records = _load_regulation_file(data)
            counts["regulation"] += len(records)
        elif isinstance(data, list) and data and "page_name" in data[0]:
            records = _load_facility_file(data)
            counts["facility"] += len(records)
        elif isinstance(data, list) and data and "category" in data[0]:
            records = _load_event_file(data)
            counts["event"] += len(records)
        else:
            print(f"  !! 경고: {path.name} 구조를 인식하지 못해 건너뜀")
            continue

        all_articles.extend(records)

    print(f"[로드 완료] 규정 조항 {counts['regulation']}개, "
          f"행사 {counts['event']}개, 시설 {counts['facility']}개 "
          f"(총 {len(all_articles)}개)")
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
    for idx, article in enumerate(articles):
        text = article["text"]
        # article_no가 없는 레코드(행사·시설)는 전역 인덱스(idx)로 유일성을 보장.
        # 규정 조항은 article_no가 있어 그대로 쓰면 사람이 읽기에도 자연스러움.
        identifier = article["article_no"] or f"item{idx}"
        base_id = f"{article['rule_id']}_{identifier}"

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
                # ChromaDB 메타데이터는 None을 허용하지 않아 모두 ""로 대체
                # (행사·시설 레코드는 article_no가 애초에 없음)
                "effective_date": article["effective_date"] or "",
                "article_no": article["article_no"] or "",
                "article_title": article["article_title"] or "",
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
