"""AJOU-VIS RAG 서버 — OpenAI 호환 /v1/chat/completions.

speech-to-speech 파이프라인의 chat-completions 백엔드가 이 서버를 가리키면
파이프라인 수정 없이 RAG가 연결된다. 흐름: rewrite → search → gate →
user_turn 조립 → 상위 LLM 호출 (docs/prompt_design.md 계약 ①~④).
"""
from __future__ import annotations

import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

import gate
import llm
import prompts_loader
import rewriter
from rag import StubRetriever, format_context

app = FastAPI(title="AJOU-VIS RAG Server")
retriever = StubRetriever()  # 태연님 ChromaDB Retriever로 교체 지점

MAX_HISTORY_TURNS = 3  # 계약 ④: 최근 2~3턴만


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "ajou-vis"
    messages: list[Message]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False  # v1은 비스트리밍만 지원


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


@app.get("/health")
def health():
    return {"status": "ok", "retriever": type(retriever).__name__}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    history, utterance = _split_request(req.messages)
    if not utterance:
        return _openai_response("질문을 인식하지 못했어요. 다시 말씀해 주세요!", req.model)

    lang = prompts_loader.detect_lang(utterance)

    # ④ 팔로업 재작성 → 검색 필요 여부 판정
    question, need_search = rewriter.rewrite(history, utterance, llm.chat)

    # ② 검색 → ① 신뢰도 게이트
    hits = retriever.search(question) if need_search else []
    if need_search and not gate.passes(hits):
        return _openai_response(gate.deferral_message(lang), req.model)

    # ③ 사용자 턴 조립 → 고정 시스템 프롬프트로 상위 LLM 호출
    user_msg = prompts_loader.user_turn(
        history=history, lang=lang, question=question,
        context=format_context(hits),
    )
    answer = llm.chat(
        system=prompts_loader.system_prompt(lang),
        user=user_msg,
        max_tokens=req.max_tokens or 300,
        temperature=req.temperature if req.temperature is not None else 0.3,
    )
    return _openai_response(answer, req.model)
