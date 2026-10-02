"""AJOU-VIS RAG 서버 — OpenAI 호환 /v1/chat/completions.

speech-to-speech 파이프라인의 chat-completions 백엔드가 이 서버를 가리키면
파이프라인 수정 없이 RAG가 연결된다. 흐름: rewrite → search → gate →
user_turn 조립 → 상위 LLM 호출 (docs/prompt_design.md 계약 ①~④).

스트리밍(SSE)을 지원한다 — 파이프라인이 stream=True로 호출하면 답변 토큰이
생성되는 대로 내려보내 TTS가 첫 문장부터 합성을 시작할 수 있다.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # gate/llm이 import 시점에 환경변수를 읽으므로 먼저 로드

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import gate
import llm
import prompts_loader
import rewriter
import smalltalk
from rag import ChromaRetriever, StubRetriever, format_context

app = FastAPI(title="AJOU-VIS RAG Server")

# corpus/chroma_db가 구축되어 있으면 실제 검색, 없으면 스텁(전부 보류 응답)
_CHROMA_DIR = Path(__file__).resolve().parent.parent / "corpus" / "chroma_db"
retriever = ChromaRetriever(_CHROMA_DIR) if _CHROMA_DIR.exists() else StubRetriever()

MAX_HISTORY_TURNS = 3  # 계약 ④: 최근 2~3턴만


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "ajou-vis"
    messages: list[Message]
    max_tokens: int | None = None
    temperature: float | None = None  # 무시 (상위 LLM이 미지원)
    stream: bool = False


def _split_request(messages: list[Message]) -> tuple[str, str]:
    """요청 메시지에서 (최근 대화기록, 현재 발화)를 뽑는다.

    파이프라인이 보내는 system 메시지는 무시한다 — 시스템 프롬프트는
    이 서버가 system_ko/en.md로 관리한다(계약 ③).
    """
    turns = [m for m in messages if m.role in ("user", "assistant")]
    if not turns or turns[-1].role != "user":
        return "", ""
    current = turns[-1].content
    recent = turns[:-1][-(MAX_HISTORY_TURNS * 2):]
    label = {"user": "사용자", "assistant": "치토"}
    history = "\n".join(f"{label[m.role]}: {m.content}" for m in recent)
    return history, current


# ── OpenAI 형식 응답 (비스트리밍 / SSE 청크) ──────────────────────────

def _openai_response(text: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
    }


def _sse_chunk(id_: str, model: str, delta: dict, finish: str | None = None) -> str:
    payload = {
        "id": id_,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _stream_pieces(pieces, model: str):
    """텍스트 조각 이터러블을 OpenAI 스트리밍 형식(SSE)으로 변환."""
    id_ = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    yield _sse_chunk(id_, model, {"role": "assistant", "content": ""})
    for piece in pieces:
        if piece:
            yield _sse_chunk(id_, model, {"content": piece})
    yield _sse_chunk(id_, model, {}, finish="stop")
    yield "data: [DONE]\n\n"


def _respond(text: str, req: ChatRequest):
    """정형 응답(보류·오류 안내) — stream 요청이면 단일 청크 SSE로."""
    if req.stream:
        return StreamingResponse(_stream_pieces([text], req.model),
                                 media_type="text/event-stream")
    return _openai_response(text, req.model)


# ── 엔드포인트 ────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "retriever": type(retriever).__name__}


@app.get("/warmup")
def warmup():
    """임베딩 모델(~10초)을 미리 로드해 첫 음성 질문의 지연을 없앤다. LLM 호출 없음."""
    hits = retriever.search("휴학", top_k=1)
    return {"status": "ok", "loaded_hits": len(hits)}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    history, utterance = _split_request(req.messages)
    if not utterance:
        return _respond("질문을 인식하지 못했어요. 다시 말씀해 주세요!", req)

    lang = prompts_loader.detect_lang(utterance)

    system = prompts_loader.system_prompt(lang)
    max_tokens = req.max_tokens or 300

    # 인사·잡담은 검색·게이트를 건너뛰고 치토가 바로 응대한다
    if smalltalk.is_smalltalk(utterance):
        user_msg = prompts_loader.user_turn(
            history=history, lang=lang, question=utterance, context="",
        ) + "\n\n" + smalltalk.NOTE.get(lang, smalltalk.NOTE["en"])
        return _llm_respond(system, user_msg, max_tokens, req)

    # ④ 팔로업 재작성 → 검색 필요 여부 판정
    question, need_search = rewriter.rewrite(history, utterance, llm.chat)

    # ② 검색 → ① 신뢰도 게이트
    hits = retriever.search(question) if need_search else []
    if need_search and not gate.passes(hits):
        return _respond(gate.deferral_message(lang), req)

    # ③ 사용자 턴 조립 → 고정 시스템 프롬프트로 상위 LLM 호출
    user_msg = prompts_loader.user_turn(
        history=history, lang=lang, question=question,
        context=format_context(hits),
    )
    return _llm_respond(system, user_msg, max_tokens, req)


def _llm_respond(system: str, user_msg: str, max_tokens: int, req: ChatRequest):
    if req.stream:
        pieces = llm.chat_stream(system=system, user=user_msg, max_tokens=max_tokens)
        return StreamingResponse(_stream_pieces(pieces, req.model),
                                 media_type="text/event-stream")

    answer = llm.chat(system=system, user=user_msg, max_tokens=max_tokens)
    return _openai_response(answer, req.model)
