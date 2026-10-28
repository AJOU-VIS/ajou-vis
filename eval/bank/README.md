# 100문항 평가 (한·영)

평가 문항집(`eval/question_bank.xlsx`)의 100문항을 **실제 RAG 경로**로 한국어·영어 모두 돌리고, 채점 초안을 만든 뒤 사람이 검토해 문항집에 기록한다.
같은 문항을 두 언어로 묻기 때문에 그대로 **한·영 A/B 테스트**가 된다. 서버 호출·단계 기록·자동 점검은 스모크 테스트(`eval/smoke/run_smoke.py`)를 그대로 쓴다.

## 실행 (저장소 루트, cmd)

```bat
server\.venv\Scripts\python eval\bank\run_bank.py
server\.venv\Scripts\python eval\bank\run_bank.py --lang ko --only 1,2,49
server\.venv\Scripts\python eval\bank\run_bank.py --rejudge eval\bank\results\<결과>.json
server\.venv\Scripts\python eval\bank\run_bank.py --fill eval\bank\results\<결과>.json
```

- 전체 실행은 답변 200회와 채점 초안 200회를 호출한다. `claude-opus-5`(effort low) 기준 약 $8.
- `--rejudge`: 저장된 답변으로 채점 초안만 다시 만든다 (채점 지시를 고쳤을 때). `--suspect`를 붙이면 X·확신 낮음·한·영 판정이 갈린 초안만 다시 채점한다. 검색결과 본문은 같은 검색어로 다시 찾아 복원한다.
- `--resume`: 크레딧 부족 등으로 멈춘 실행을 이어서 돌린다. 답변은 하나마다 저장된다.
- `--fill`: 검토를 반영한 판정을 문항집에 쓴다. 한국어 → `문항집` 시트 J·K·L 열(정답·근거 제시·응답 요약), 영어 → `영어 채점` 시트. `집계` 시트는 한국어 기준으로 자동 계산된다.
- 사전 조건: 스모크와 같음 (`server/.env`, `corpus/chroma_db`) + `openpyxl` (`server\.venv\Scripts\python -m pip install openpyxl`).

## 채점

채점 규칙은 문항집 `안내` 시트와 같다.

| 열 | 일반 문항 | 함정-무근거 문항 |
|---|---|---|
| 정답 O/X | 사실이 기대 정답·판정 기준에 맞으면 O | 지어내지 않고 담당 부서·포탈로 안내하면 O |
| 근거·출처 제시 O/X/NA | 문서·조항·안내 페이지 이름을 밝혔으면 O, 아니면 X (범위 밖·보류 답은 NA) | 항상 NA |

1. **Claude 초안**: 문항마다 기대 정답·판정 기준·답변·검색결과 상위 3개 본문을 보고 판정과 확신(high/low)을 매긴다. 도서관 좌석 질문은 실시간 데이터로 답했다고 알려 준다. 함정 문항의 근거 제시는 코드에서 NA로 고정한다.
2. **사람 검토**: 결과 `.md`의 "검토가 필요한 초안"(확신 낮음)과 "한·영 정답 판정이 갈린 문항"을 읽는다. 바꿀 판정만 같은 이름의 `_review.json`에 적는다.

   ```json
   {"49-ko": {"correct": "X", "evidence": "NA", "memo": "유학생 학비를 먼저 말함"}}
   ```
3. `--fill`로 문항집에 기록하면 리포트(`.md`)도 검토 반영본으로 다시 만들어진다.

## 결과

`results/bank_<날짜-시각>_<모델>.json`(원자료: 답변, 경로, 검색 상위, 자동 점검, 채점 초안)과 같은 이름의 `.md`(언어별·영역별 요약, 검토할 문항, 문항별 상세). `results/`는 git에 올리지 않는다. 공유할 수치는 `docs/`로 옮긴다.
