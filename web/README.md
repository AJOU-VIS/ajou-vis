# 치토 웹 화면 (`web/`)

ChatGPT형 대화 + 오른쪽 치토 스테이지(상황별 표정) + 마이크 + 텍스트 입력. 브라우저만 있으면 PC·휴대폰에서 치토와 음성·텍스트로 대화한다.
설계: 팀 Drive `웹 화면 설계/chito_web_design.html` (v0.1, 플랫) · 담당: 진주영

```
브라우저 ──(주소 하나)──▶ web/server.py :7860
                          ├─ /              화면 (static/)
                          ├─ /v1/realtime   ─▶ speech-to-speech serve :8765  (음성 인식·LLM 슬롯·TTS)
                          └─ /api/turn      ─▶ RAG 서버 :8100 /v1/turns/latest (출처·처리 경로·연락처, 읽기 전용)
```

- 답 글자와 소리는 실시간 연결로, 출처 카드·담당 부서 연락처·치토 표정은 답이 끝난 뒤 RAG 서버 턴 기록(`server/turns.py`)으로 받아 붙인다.
- **프롬프트·페르소나는 바꾸지 않는다.** 화면이 보내는 지시문은 RAG 서버가 버리고(`server/app.py` `_split_request`), 화면용 긴 내용은 이미 검색된 근거 원문을 펼쳐 보이는 방식이다.
- 실시간 연결 코드는 speech-to-speech `demo/`에서 수정 없이 가져왔다 (`static/realtime/NOTICE.md`). 치토용 기능(텍스트 질문·끊기·답 소리 끄기)은 `static/chito-client.js`.
- 세션에 목소리(voice)를 보내지 않는다 — 보내면 기준 음성 복제 대신 다른 화자로 바뀔 수 있다.

## 처음 한 번

```bat
cd web
npm ci
..\server\.venv\Scripts\python scripts\prepare_assets.py "<팀 Drive의 치토 PNG 폴더>"
```

- `npm ci`: 브라우저용 OpenAI Agents SDK 번들(@openai/agents 0.14.3, demo와 같은 버전). `node_modules/`는 커밋하지 않는다.
- 치토 표정 이미지(`static/assets/chito/`)는 홍보실 약속대로 레포에 넣지 않는다 (`.gitignore`).
- 파이썬 패키지는 RAG 서버 가상환경(`server/.venv`)에 있는 fastapi·uvicorn·websockets·httpx를 그대로 쓴다.

## 실행

```bat
rem 저장소 루트에서 (RAG 서버 :8100, 음성 서버 :8765가 떠 있어야 실제 대화가 된다)
server\.venv\Scripts\python -m uvicorn server:app --app-dir web --port 7860
```

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `S2S_URL` | `ws://127.0.0.1:8765/v1/realtime` | speech-to-speech serve 실시간 주소 |
| `RAG_URL` | `http://127.0.0.1:8100` | RAG 서버 (턴 기록만 읽는다) |
| `WEB_PASSCODE` | (없음) | 접속 비밀번호. 고정 주소로 공개할 때는 꼭 설정 (API 비용) |
| `PORTAL_URL` | (없음) | 범위 밖 답에 보여 줄 학사서비스 포탈 주소. 검색 자료에 없어 비워 두면 버튼을 숨긴다 |

## Colab에서 (GPU 음성 서버 + 웹 화면)

`server/colab_voice_server.ipynb`를 1번부터 실행하면 8-1번 셀이 웹 서버와 터널을 띄우고 **치토 웹 화면 주소**를 출력한다.

- 1번 셀: `WEB_ENABLE = True`, `CHITO_PNG_DIR = "<Drive의 치토 PNG 폴더>"` (비우면 표정 이미지 없이 뜬다). 아직 main에 병합 전이면 `RAG_BRANCH = "feat/web-ui"`.
- 보안 비밀(선택): `WEB_PASSCODE`(접속 비밀번호), `NGROK_AUTHTOKEN` + `NGROK_DOMAIN`(ngrok 무료 고정 도메인 → 매번 같은 주소). ngrok이 없으면 cloudflared 임시 주소.
- SDK 번들은 npm 없이 같은 고정 버전 파일만 받아 `web/vendor/`에 둔다 (npm 번들과 같은 파일, sha256 확인).
- 터미널 접속(8번 셀, `run_talk_colab.bat`)은 그대로 함께 쓸 수 있다.

## 서버 없이 화면만 보기 (비용 없음)

`http://localhost:7860/?mock=answer` — 11/3 마지막 스모크의 실제 답과 같은 질문의 실제 검색 결과로 대화를 흉내 낸다 (`static/mock/fixtures.json`).

| `?mock=` | 화면 |
|---|---|
| `hello` | 시작 화면 |
| `listen` | 음성 질문 듣는 중 (모바일은 음성 모드) |
| `answer` | 근거 있는 답 + 출처 카드 (음성 질문) |
| `contact` | 근거 있는 답 + 담당 부서 연락처 (한·영 섞인 텍스트 질문) |
| `sorry` | 보류 + 연락처 |
| `noscope` | 범위 밖 (개인정보) |
| `crisis` | 위기 발화 — 상담 전화 카드 |
| `en` | 영어 질문·답 |

데이터를 새 스모크 결과로 바꾸려면: `server\.venv\Scripts\python web\scripts\make_mock_fixtures.py eval\smoke\results\<결과>.json`

## 화면 상태 (설계 보드와 같음)

| 상황 | 치토 표정 | 신호 |
|---|---|---|
| 처음·잡담 | 29.인사 | 처리 경로 `smalltalk` |
| 듣는 중 | 10.궁금 | `user-turn-started` |
| 찾는 중 | 22.독서 | `user-turn-stopped` · 텍스트 보냄 |
| 답변 | 16.안내 | 답 글자가 오는 중 · 턴 `kind=answer` |
| 보류 | 27.미안해 | 턴 `kind=sorry` (게이트 보류·"자료로는 확실하지 않아요") |
| 범위 밖 | 15.금지 | 턴 `kind=noscope` |
| 위기 발화 | 7.애 | 턴 `kind=crisis` |
| 오류·끊김 | 11.놀람 | 연결 오류 |

## 알려진 한계

- 텍스트로만 쓰다가 마이크를 처음 켜면 음성 서버에 새로 연결해, 음성 서버 쪽 대화 맥락이 처음부터 시작된다.
- 여러 명이 동시에 쓰면 `/api/turn`이 다른 사람의 턴을 가져올 수 있다 (턴 번호로만 구분). 시연·소수 사용 기준.
- "다시 듣기"는 넣지 않았다 — 답 소리를 저장하지 않아 다시 들려주려면 LLM을 한 번 더 불러야 한다.
