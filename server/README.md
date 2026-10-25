# RAG 서버 (OpenAI 호환 엔드포인트)

speech-to-speech 파이프라인의 LLM 슬롯에 그대로 꽂히는 OpenAI 호환 서버.
프롬프트 계약(`docs/prompt_design.md` 4장)을 구현 스펙으로 따른다.

## 한 턴 처리 흐름

```
POST /v1/chat/completions (파이프라인이 호출)
  → 요청에서 현재 발화 + 최근 대화 추출
  → [rewrite] 팔로업이면 독립 질문으로 재작성 (prompts/rewrite.md)
      · [NO_SEARCH]면 검색 생략 (형태 변경 요청)
  → [search] RAG 검색 (rag.py — ChromaDB 연결부, 현재 스텁)
  → [gate]   신뢰도 게이트: 검색결과 없음/임계값 미달 → LLM 호출 없이
             "담당 부서 안내" 정형 응답 반환 (계약 ①, 무근거 회피 1차 차단)
  → [assemble] prompts/user_turn.md 조립 (대화기록+현재질문+검색결과)
  → [llm]    system_ko/en.md(고정) + user_turn(가변)으로 상위 LLM 호출
  → OpenAI 형식 응답 반환 → 파이프라인이 TTS로
```

## 실행

```bash
cd server
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY 입력 (키는 절대 커밋 금지)
uvicorn app:app --port 8100
```

상위 LLM은 Anthropic Claude(공식 SDK)를 사용한다. 기본 모델 `claude-opus-5`,
음성 지연을 고려해 effort 기본 `low` — `.env`에서 변경 가능.

파이프라인 연결 (chat-completions 백엔드를 이 서버로):

```bash
speech-to-speech local ... \
  --llm_backend chat-completions \
  --chat_completions_api_base http://127.0.0.1:8100/v1
```

(정확한 플래그명은 `speech-to-speech local --help`의 chat-completions 항목 참조)

## 구성 요소

| 파일 | 역할 | 계약 |
|---|---|---|
| `app.py` | OpenAI 호환 엔드포인트, 턴 오케스트레이션 | ③ 사용자 턴 주입 |
| `prompts_loader.py` | `../prompts/*.md` 로드, 자리표시자 채움 | ③, ④ |
| `rewriter.py` | 팔로업 재작성, `[NO_SEARCH]` 판정 | ④ 멀티턴 |
| `rag.py` | 검색 인터페이스 + 스텁 (ChromaDB 연결 지점) | ② 출력 형식 |
| `gate.py` | 신뢰도 게이트 + 정형 보류 응답 | ① 이중 강제 |
| `llm.py` | 상위 LLM(OpenAI 호환 API) 클라이언트 | |

## RAG 검색 (rag.py)

`ChromaRetriever`가 `corpus/chroma_db`(embed_corpus.py가 구축, BGE-M3)를 검색한다.
DB가 없으면 자동으로 `StubRetriever`(빈 결과 → 전부 보류 응답)로 동작하므로,
서버를 처음 쓰는 팀원은 먼저 `corpus/scripts/embed_corpus.py`를 실행해 DB를 만들 것.
점수는 정규화 임베딩의 L2 거리를 코사인 유사도로 변환한 값(0~1)이며
게이트 임계값(GATE_SCORE_THRESHOLD) 판단에 쓰인다. 임베딩 모델(~2GB)은
첫 검색 시 지연 로드된다.

## 미정/후속

- 스트리밍 응답(SSE) — v1은 비스트리밍, 파이프라인 연동 확인 후 추가
- {{LANG}} — v1은 한글 포함 여부로 ko/en 판별, 파이프라인이 언어코드를 넘겨주는 경로 확인 후 교체
