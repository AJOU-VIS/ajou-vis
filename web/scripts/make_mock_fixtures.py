"""화면 확인용 가짜 대화(?mock=...) 데이터를 만든다 — LLM 호출 없음, 비용 없음.

치토 답은 11/3 마지막 스모크(프롬프트 v2)에서 실제로 나온 답이고, 출처·연락처·표정은 같은 질문을
지금 검색 DB로 다시 검색해 서버(server/turns.py)가 화면에 줄 형식 그대로 만든다.

실행 (저장소 루트):  server\\.venv\\Scripts\\python web\\scripts\\make_mock_fixtures.py eval\\smoke\\results\\<결과>.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
from rag import ChromaRetriever  # noqa: E402
import turns  # noqa: E402

# 화면 시나리오 → 스모크 케이스 ID, 질문 방법(음성·텍스트)
SCENARIOS = {
    "answer": ("C4", "voice"),
    "contact": ("E3", "text"),
    "sorry": ("B3", "text"),
    "noscope": ("X8", "text"),
    "crisis": ("X12", "voice"),
    "en": ("V3", "text"),
    "greet": ("E4", "voice"),
}

rows = {r["id"]: r for r in json.load(open(sys.argv[1], encoding="utf-8"))["results"]}
retriever = ChromaRetriever(ROOT / "corpus" / "chroma_db")
out = {}
for name, (case_id, via) in SCENARIOS.items():
    r = rows[case_id]
    path = r["path"] if r["path"] != "rewrite" else "llm"
    hits = [] if path in ("crisis", "smalltalk") else retriever.search(r.get("search_query") or r["question"])
    out[name] = {
        "case": case_id,
        "via": via,
        "question": r["question"],
        "answer": r["answer"],
        "turn": {
            "seq": 0,
            "lang": r.get("answer_lang", r["lang"]),
            "path": path,
            "kind": turns.classify(path, r["answer"]),
            "sources": turns.sources_of(hits, r["answer"]) if hits else [],
            "contacts": turns.contacts_of(r["answer"]),
        },
    }
    print(name, case_id, out[name]["turn"]["kind"], [s["doc"] for s in out[name]["turn"]["sources"][:2]],
          [c["dept"] for c in out[name]["turn"]["contacts"]])

dst = ROOT / "web" / "static" / "mock" / "fixtures.json"
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("→", dst.relative_to(ROOT))
