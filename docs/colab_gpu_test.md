# Colab GPU 음성 서버 테스트 기록

- 일시: 2026-10-05
- 구성: STT·RAG 서버·TTS를 Colab GPU에서 실행, Mac은 마이크·스피커만 연결 (cloudflared 터널)
  - 노트북: `server/colab_voice_server.ipynb` / Mac 접속: speech-to-speech 포크 `run_talk_colab.sh`
  - STT whisper-large-v3-turbo (CUDA, float16) · LLM claude-haiku-4-5 · TTS Qwen3-TTS GGML Q8_0 (Sohee, 문장 단위 합성)

## 결과 요약

**말 끝 → 첫 음성이 Mac 로컬 8.2~9.4초에서 Colab GPU 2.0~2.7초로 단축** (질문 6개 평균 약 2.4초).

| 항목 | Mac 로컬 (MLX) | Colab GPU | 변화 |
|---|---|---|---|
| 말 끝 → 첫 음성 | 8.2~9.4초 | 2.0~2.7초 | 약 3~4배 |
| STT | 2.9~3.2초 | 0.2~0.8초 | 약 5~10배 |
| TTS 속도 (RTF) | 약 1.9배속 | 약 7배속 | 약 3.7배 |
| 짧은 문장 늘어짐 | 9.6초 한도까지 늘어남 | 없음 ("안녕하세요!" 0.84초) | 해결된 것으로 보임 |

- "말 끝 → 첫 음성"은 파이프라인 로그의 `Last speech detected to first speech out` 값 중 각 질문의 첫 문장 기준.
- `bench/latency_report.py`의 표(평균 4.44초)는 "LLM 완료 후 TTS 시작"을 가정해 문장 단위 스트리밍에서는 실제보다 크게 계산됨 → 도구 수정 필요.
- TTS 늘어짐이 Colab(GGML Q8_0)에서 재현되지 않음 → Mac의 MLX 6bit 환경 문제였을 가능성이 큼.
- Mac에서 "휴양·추앙"으로 오인식되던 "휴학"이 이번에는 정확히 인식됨 (표본이 적어 추가 확인 필요).

## 발견된 문제

| 문제 | 내용 | 대응안 |
|---|---|---|
| 짧은 한국어를 중국어로 인식 | "고마워" 등이 "不麻烦", "恐怕我"로 받아적힘 → 서버가 영어 질문으로 판단해 영어로 응답 | 언어 자동 감지를 한국어·영어로 제한 (외국인 학생 지원을 위해 영어는 유지) |

## Colab 환경 세팅 중 해결한 문제

| 문제 | 원인 | 해결 |
|---|---|---|
| ajou-vis 클론 실패 | 비공개 레포 | Colab 보안 비밀 `GITHUB_TOKEN`(읽기 전용)으로 클론 |
| RAG 서버 500 에러 | `claude-haiku-4-5`가 `effort` 파라미터 미지원 | 미지원 모델에는 effort 생략 (`server/llm.py`) |
| TTS 로드 실패 (`libcudart.so.12` 없음) | Colab의 CUDA 버전과 GGML 바이너리 기대 버전(CUDA 12) 불일치 | ldd로 빠진 라이브러리 검사 후 CUDA 12 런타임 pip 설치 + LD_LIBRARY_PATH 등록 |
| Mac 접속 시 API 키 에러 | talk 클라이언트가 외부 주소 접속 시 키 요구 | 접속 스크립트에 임시 키 전달 (서버는 키 검사 안 함) |

## 다음 할 일

1. 언어 감지를 한국어·영어로 제한
2. 지연 측정 도구를 문장 단위 스트리밍에 맞게 수정
3. Whisper vs Qwen3-ASR을 Colab GPU에서 비교 (노트북 1번 셀에서 선택)
