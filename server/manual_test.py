"""수동 검증 스크립트 — 실제 Anthropic API를 호출한다 (소액 과금 주의).

server/.env에 유효한 ANTHROPIC_API_KEY가 있어야 한다.
실행: cd server && python manual_test.py

검증 항목 (docs/prompt_design.md 계약):
  1. 꼬리질문 재작성 (④)          2. 형태 변경 → [NO_SEARCH] (④)
  3. 가짜 검색결과 → 근거 인용 답변 (②③)   4. 근거 없음 → 게이트 차단 (①)

2026-09-27 검증 완료: 4항목 모두 통과 — 부분 근거 시 조항에 없는 내용(신청 방법·일정)은
지어내지 않고 포탈 안내로 전환하는 것까지 확인.
"""
from fastapi.testclient import TestClient

import app
import llm
import rewriter
from rag import SearchHit

client = TestClient(app.app)

print("=== 1. rewrite: 꼬리질문 → 독립 질문 ===")
history = "사용자: 휴학 신청 기간이 언제야?\n치토: 학사요람에 따르면 휴학 신청은 개강 후 4주 이내에 가능해요."
q, need, _source = rewriter.rewrite(history, "그럼 복학은?", llm.chat)
print(f"재작성: {q!r} / 검색 필요: {need}")

print("\n=== 2. rewrite: 형태 변경 요청 → NO_SEARCH ===")
q2, need2, _source2 = rewriter.rewrite(history, "방금 답 영어로 말해줘", llm.chat)
print(f"재작성: {q2!r} / 검색 필요: {need2}")

print("\n=== 3. 가짜 검색결과 주입 → 근거 인용 답변 (전체 경로) ===")


class FakeRetriever:
    def search(self, question, top_k=5):
        return [SearchHit(
            source_name="아주대학교 학칙", article="제38조",
            text="휴학은 통산 3년을 초과할 수 없으며, 복학하고자 하는 자는 "
                 "휴학기간 만료 전 소정 기간 내에 복학원을 제출하여야 한다.",
            score=0.87)]


app.retriever = FakeRetriever()
r = client.post("/v1/chat/completions", json={
    "messages": [{"role": "user", "content": "복학 신청은 어떻게 해?"}]})
print("상태코드:", r.status_code)
print("응답 원문:", r.text)
print("치토:", r.json()["choices"][0]["message"]["content"])

print("\n=== 4. 근거 없는 질문 → 게이트 차단 (LLM 호출 없음) ===")


class EmptyRetriever:
    def search(self, question, top_k=5):
        return []


app.retriever = EmptyRetriever()
r = client.post("/v1/chat/completions", json={
    "messages": [{"role": "user", "content": "기숙사 세탁실은 몇 층이야?"}]})
print("치토:", r.json()["choices"][0]["message"]["content"])
