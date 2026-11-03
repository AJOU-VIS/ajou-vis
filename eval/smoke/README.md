# 스모크 테스트 (프롬프트 계약 점검)

시스템 프롬프트의 답변 판단 구간(A/B/C/D)과 멀티턴 규칙이 **실제 RAG 검색 결과**에서 지켜지는지 빠르게 확인하는 61개 케이스.
100문항 평가 문항집(`eval/question_bank.xlsx`) 전에 프롬프트를 고칠 때마다 돌리는 회귀 점검용이다.

- 처음 22개(A~M) + 프롬프트 v2 확인용 V1~V5 (11/3)
- 마지막 검증용 34개 (11/3, `kind` 필드): 정상 N · 코너 K · 엣지 E · 에러 X — 학번 경계, 두 가지를 한 번에 묻기, 한 단어·오타·한영 혼용, 같은 대화 안 한↔영 전환, 연락처 요청, 지시 무시·지시문 공개 요청, 잘못된 전제, 범위 밖, 감정 표현·빈말, 위기 발화(한·영). 결과는 `docs/eval_100_ko_en.md` 8절.

## 실행 (저장소 루트, cmd)

```bat
server\.venv\Scripts\python eval\smoke\run_smoke.py --dry-run
server\.venv\Scripts\python eval\smoke\run_smoke.py
server\.venv\Scripts\python eval\smoke\run_smoke.py --only B,D
server\.venv\Scripts\python eval\smoke\run_smoke.py --model claude-sonnet-5-5
server\.venv\Scripts\python eval\smoke\run_smoke.py --recheck eval\smoke\results\<결과>.json
```

- `--dry-run`: LLM 없이 잡담 판정·검색 점수·게이트만 (과금 없음). 케이스를 추가했거나 게이트 임계값을 바꿨을 때 먼저 확인.
- 전체 실행은 Claude API를 호출한다. `claude-opus-5`(effort low) 기준 61개에 약 $2 (v2 프롬프트, 11/3). 일부만 돌릴 때는 `--only`.
- `--model`: 같은 케이스를 다른 모델로 돌릴 때만 사용. 팀 평가 기준 모델은 `claude-opus-5`(서버 기본값)다.
- 서버의 답변 문장 수 상한(`MAX_SENTENCES`)이 켜져 있어도 문장 수 점검은 상한 적용 **전** LLM 원답 기준이다 — 프롬프트 규칙을 지켰는지와 서버가 막아줬는지를 구분하기 위해서.
- `--recheck`: `cases.json`이나 점검 규칙을 고친 뒤 저장된 답변으로 리포트만 다시 만든다 (과금 없음).
- 사전 조건: `server/.env`에 API 키, `corpus/chroma_db` 구축 (`corpus/scripts/embed_corpus.py`).

## 구간

| 구간 | 의미 | 기대 동작 |
|---|---|---|
| A | 근거 충분 | 답변 + 출처를 문장 앞에 |
| B | 근거 부분·조건 상이 | 확인된 부분만, 갈리는 지점(학번·과정)은 단정하지 않고 확인 안내 |
| C-gate | 근거 없음 | 서버 게이트가 차단 → 정형 보류 멘트 (프롬프트 무관) |
| C-prompt | 게이트는 통과, 답할 근거는 없음 | 프롬프트가 보류 — 지어내지 않고 부서·포탈 안내 |
| D | 범위 밖 (신청·개인정보) | 처리하지 않고 포탈 안내 |
| M | 멀티턴·잡담 경로 | 꼬리질문 재작성, `[NO_SEARCH]` 형태 변경, 인사, 위기 발화(`crisis` 경로 — LLM 없이 고정 상담 안내) |

## 자동 점검

결과의 ❌(실패)는 규칙 위반, ⚠️(경고)는 사람이 맥락을 봐야 하는 것. **최종 O/X는 리포트 상세를 읽고 사람이 판정한다.**

- 실패: 게이트·경로가 기대와 다름, 필수 키워드 누락, 답변 잘림(출력 토큰 상한), 줄바꿈·마크다운, 검색 점수·개정 날짜 읽기, 문장 4개 이상, 묻지 않은 인사, 응답 언어 불일치, 출처 표기 없음(A·B), 검색결과에 없는 부서명, 프롬프트·태그가 답변에 섞임
- 실패(v1.4b 추가, 10/27 음성 테스트): 괄호, 물결표(~) 범위 표기, 합니다체 섞임, 검색결과에 없는 조항 번호를 출처로 댐
- 실패(v2 추가, 11/3): 검색결과 5개 어디에도 없는 전화번호·이메일, LLM 원답 세 문장 이상 (v2는 최대 두 문장 — "9 a.m." 같은 영어 약어의 마침표와 인사 턴 맨 앞 "Hi!"는 세지 않음). 기본 안내처(교무팀·교학팀·재무회계팀·학생지원팀·유학생입학팀)는 검색결과에 없어도 지어낸 부서로 보지 않는다.
- 경고: `watch_for` 문자열 등장, 음성 기준 길이 초과(목표 약 12초 = 한국어 80자·영어 30단어에 여유를 둔 100자 / 40단어 — `run_smoke.py`의 `MAX_KO_CHARS`, `MAX_EN_WORDS`), 페르소나 말투(상대 높임 '-시-' 섞임, 인사가 아닌데 느낌표 — v2.3)
- 결과 파일에는 LLM이 받은 검색결과 5개를 모두 남긴다 (10/28까지는 상위 3개만 남겨 4·5번째 근거를 놓친 판정이 있었다).

## 결과

`results/smoke_<날짜-시각>_<모델>.md`(사람용, 판정 칸 포함)와 같은 이름의 `.json`(원자료: 재작성 질문, 검색 상위 조항·점수, LLM 토큰·시간·stop_reason). `results/`는 git에 올리지 않는다(.gitignore) — 공유할 결과는 docs/나 팀 Drive로 옮긴다.

두 결과의 전후 비교표(프롬프트 버전별·모델별):

```bat
server\.venv\Scripts\python eval\smoke\compare.py eval\smoke\results\<이전>.json eval\smoke\results\<이후>.json
```

## 케이스 추가

`cases.json`의 `cases`에 항목을 넣는다. 필드 설명은 파일 상단 `fields`. 질문은 **현재 코퍼스에 들어 있는 규정 범위**에서 내야 A·B로 의미가 있다 — 코퍼스에 없는 문서(예: 학사요람)를 묻는 질문은 C가 된다.
