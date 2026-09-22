<!--
AJOU-VIS 사용자 턴 템플릿 · v1.1 (언어 공용)
용도: 매 턴 server가 채워 LLM에 '사용자 메시지'로 전달한다. 시스템 프롬프트(system_ko/en.md)는 고정,
      이 템플릿만 매 턴 바뀐다. (검색결과는 사용자 턴에 주입 — docs/prompt_design.md)
채우는 값(server):
  {{RECENT_HISTORY}}    최근 2~3턴(사용자/치토 발화). 첫 턴이면 비움. 넘치면 오래된 턴부터 버리거나 요약.
  {{LANG}}              현재 질문 언어 코드(ko / en) — rewrite 단계에서 감지
  {{CURRENT_QUESTION}}  이번 턴 질문. rewrite.md로 독립 질문 재작성된 결과(재작성 불필요 시 원문).
  {{RETRIEVED_CONTEXT}} 이번 턴 RAG 결과. 각 항목 [출처: 문서명, 조항/URL] (점수: 0.00).
                        형태 변경 요청(rewrite가 [NO_SEARCH])이거나 검색 결과 없으면 비움.
-->
<대화기록>
{{RECENT_HISTORY}}
</대화기록>

<현재질문 language="{{LANG}}">
{{CURRENT_QUESTION}}
</현재질문>

<검색결과>
{{RETRIEVED_CONTEXT}}
</검색결과>