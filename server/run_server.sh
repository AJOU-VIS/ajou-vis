#!/bin/zsh
# AJOU-VIS RAG 서버 실행 (별도 터미널용). 종료: Ctrl+C
# 기동 후 몇 초 뒤 /warmup을 자동 호출해 임베딩 모델(~10초)을 미리 로드한다.
cd "$(dirname "$0")"
( sleep 4; curl -s http://127.0.0.1:8100/warmup > /dev/null && echo "[warmup] 임베딩 모델 로드 완료" ) &
exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8100
