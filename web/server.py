"""치토 웹 화면 서버 — 화면 파일 + 실시간 음성 연결 중계 + 턴 정보 중계 (11/3).

브라우저는 이 서버 하나에만 접속한다 (터널·고정 주소 1개면 된다):
  /                      화면 (static/)
  /vendor/openai-realtime-agents.umd.js   OpenAI Agents SDK 브라우저 번들 (web/에서 npm ci, 커밋하지 않음)
  /api/config            화면 설정 (비밀번호 필요 여부)
  /api/login             비밀번호 확인 → 쿠키
  /api/turn?after=N      RAG 서버의 마지막 턴 정보(출처·처리 경로·연락처) 읽기 전용 중계
  /v1/realtime           speech-to-speech serve 로 웹소켓 중계

환경변수
  S2S_URL       음성 서버 실시간 주소 (기본 ws://127.0.0.1:8765/v1/realtime)
  RAG_URL       RAG 서버 주소 (기본 http://127.0.0.1:8100) — /v1/turns/latest 만 부른다
  WEB_PASSCODE  접속 비밀번호. 비우면 비밀번호 없이 열린다 (고정 주소로 공개할 때는 꼭 설정)
  PORTAL_URL    범위 밖 답(신청·개인정보)에 보여 줄 학사서비스 포탈 주소. 비우면 버튼을 숨긴다
                (검색 자료에 포탈 주소가 없어 코드에 넣지 않았다)

실행 (web/ 에서):  uvicorn server:app --port 7860
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
# 브라우저 SDK 번들: npm ci 결과, 없으면 같은 고정 버전 파일 하나만 받아 둔 vendor/ (Colab 노트북 8-1번 셀)
SDK_BUNDLES = [
    HERE / "node_modules/@openai/agents-realtime/dist/bundle/openai-realtime-agents.umd.js",
    HERE / "vendor/openai-realtime-agents.umd.js",
]

S2S_URL = os.environ.get("S2S_URL", "ws://127.0.0.1:8765/v1/realtime").strip()
RAG_URL = os.environ.get("RAG_URL", "http://127.0.0.1:8100").strip().rstrip("/")
PASSCODE = os.environ.get("WEB_PASSCODE", "").strip()
PORTAL_URL = os.environ.get("PORTAL_URL", "").strip()
COOKIE = "chito_pass"

app = FastAPI(title="AJOU-VIS 치토 웹")


def _token() -> str:
    return hashlib.sha256(f"chito:{PASSCODE}".encode()).hexdigest()


def _authed(cookies) -> bool:
    return not PASSCODE or hmac.compare_digest(cookies.get(COOKIE, ""), _token())


@app.get("/vendor/openai-realtime-agents.umd.js", include_in_schema=False)
def sdk_bundle():
    path = next((p for p in SDK_BUNDLES if p.is_file()), None)
    if path is None:
        raise HTTPException(status_code=503, detail="web/ 에서 npm ci 를 먼저 실행하세요")
    return FileResponse(path, media_type="text/javascript")


@app.get("/api/config")
def config(request: Request):
    return {"needPasscode": bool(PASSCODE), "authed": _authed(request.cookies), "portalUrl": PORTAL_URL}


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    if not PASSCODE or hmac.compare_digest(str(body.get("passcode", "")), PASSCODE):
        response = JSONResponse({"ok": True})
        response.set_cookie(COOKIE, _token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
        return response
    return JSONResponse({"ok": False}, status_code=401)


@app.get("/api/turn")
async def turn(request: Request, after: int = 0):
    if not _authed(request.cookies):
        raise HTTPException(status_code=401)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{RAG_URL}/v1/turns/latest", params={"after": after})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"turn": None, "error": f"{type(e).__name__}"}


@app.websocket("/v1/realtime")
async def realtime(ws: WebSocket):
    """브라우저 ↔ speech-to-speech serve 웹소켓을 그대로 중계한다 (메시지는 건드리지 않음)."""
    if not _authed(ws.cookies):
        await ws.close(code=4401)
        return
    requested = list(ws.scope.get("subprotocols") or [])
    await ws.accept(subprotocol="realtime" if "realtime" in requested else None)
    query = ws.scope.get("query_string", b"").decode()
    upstream_url = S2S_URL + (f"?{query}" if query else "")
    try:
        async with websockets.connect(upstream_url, subprotocols=requested or None, max_size=None,
                                      open_timeout=15) as upstream:
            async def browser_to_server():
                while True:
                    message = await ws.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def server_to_browser():
                async for message in upstream:
                    if isinstance(message, str):
                        await ws.send_text(message)
                    else:
                        await ws.send_bytes(message)

            tasks = [asyncio.create_task(browser_to_server()), asyncio.create_task(server_to_browser())]
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except (OSError, websockets.WebSocketException) as e:
        print(f"[realtime] 음성 서버 연결 실패: {type(e).__name__}: {e}")
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
