"""AJOU-VIS 스모크 테스트 — 프롬프트 계약(A/B/C/D 구간·멀티턴)을 실제 RAG 경로로 점검

server/app.py의 /v1/chat/completions를 프로세스 안에서(TestClient) 그대로 호출하고,
단계별 동작(잡담 판정·재작성·검색 점수·게이트·LLM 토큰)을 함께 기록한다.
자동 점검은 형식·키워드 위주의 1차 필터다. 최종 O/X 판정은 결과 파일을 보고 사람이 한다.

실행 (저장소 루트에서, cmd):
  server\\.venv\\Scripts\\python eval\\smoke\\run_smoke.py
  
옵션:
  --dry-run                                     검색·게이트만 (비용 x)
  --only A,C-gate                               구간·케이스 ID 골라 실행
  --model claude-sonnet-5-5                     모델 설정
  --recheck eval\\smoke\\results\\<결과>.json    점검 규칙·cases.json 수정 후 리포트만 다시 생성 (비용 x)

결과: eval/smoke/results/smoke_<날짜-시각>_<모델>.md (사람용) + 같은 이름 .json (원자료)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

# 비용 추정용 단가 (USD / 1M tokens, 2026-09 공시가 기준)
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
KRW_PER_USD = 1400  # 대략치

# 임베딩 모델 로드 시 진행바·경고 줄이기 (server 모듈 import 전에 설정)
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


# ── 단계별 기록 ──────────────────────────────────────────────────

class Trace:
    """한 케이스를 처리하는 동안 서버 각 단계가 무엇을 했는지 담는다."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.smalltalk = None
        self.rewritten = None
        self.need_search = None
        self.search_query = None
        self.hits = []
        self.gate = None
        self.calls = []
        self.stage = "answer"  # 지금 진행 중인 LLM 호출의 용도 (rewrite / translate / answer)


def install_tracing(app, gate, rewriter, smalltalk, llm, trace: Trace, with_llm: bool):
    """서버 코드는 그대로 두고, 모듈 함수를 감싸서 단계별 결과를 trace에 남긴다."""
    orig_small = smalltalk.is_smalltalk

    def is_smalltalk(utterance):
        trace.smalltalk = orig_small(utterance)
        return trace.smalltalk

    smalltalk.is_smalltalk = is_smalltalk

    orig_rewrite = rewriter.rewrite

    def rewrite(history, utterance, chat):
        trace.stage = "rewrite"
        try:
            trace.rewritten, trace.need_search = orig_rewrite(history, utterance, chat)
        finally:
            trace.stage = "answer"
        return trace.rewritten, trace.need_search

    rewriter.rewrite = rewrite

    # 영어 질문은 검색 전에 한국어로 옮긴다 (server/rewriter.py search_query)
    if hasattr(rewriter, "search_query"):
        orig_search_query = rewriter.search_query

        def search_query(question, lang, chat):
            trace.stage = "translate"
            try:
                trace.search_query = orig_search_query(question, lang, chat)
            finally:
                trace.stage = "answer"
            return trace.search_query

        rewriter.search_query = search_query

    retriever = app.retriever

    class TracingRetriever:
        def search(self, question, top_k=5):
            trace.hits = retriever.search(question, top_k=top_k)
            return trace.hits

    app.retriever = TracingRetriever()

    orig_passes = gate.passes

    def passes(hits):
        trace.gate = orig_passes(hits)
        return trace.gate

    gate.passes = passes

    if with_llm:
        client = llm._get_client()
        orig_create = client.messages.create

        def create(**kwargs):
            t = time.time()
            resp = orig_create(**kwargs)
            trace.calls.append({
                "stage": trace.stage,
                "model": resp.model,
                # 서버가 문장 수 상한(sentence_limit)으로 자르기 전의 원래 답
                "text": next((b.text for b in resp.content if b.type == "text"), ""),
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "seconds": round(time.time() - t, 2),
                "stop_reason": resp.stop_reason,
            })
            return resp

        client.messages.create = create
        if client.messages.create is not create:
            sys.exit("LLM 호출 기록 설정 실패 — anthropic SDK 구조가 바뀌었는지 확인하세요.")


def path_of(trace: Trace) -> str:
    if trace.smalltalk:
        return "smalltalk"
    if trace.need_search is False:
        return "no_search"
    if trace.gate is False:
        return "gate_block"
    if any(c["stage"] == "rewrite" for c in trace.calls):
        return "rewrite"
    return "llm"


# ── 자동 점검 ────────────────────────────────────────────────────

LLM_PATHS = {"llm", "rewrite", "no_search", "smalltalk"}  # 답변을 LLM이 생성한 경로
SEARCH_PATHS = {"llm", "rewrite"}  # 검색결과를 근거로 답한 경로

# 음성 길이 기준 — v1.4b 목표는 약 12초(한국어 80자 안팎, 영어 30단어 안팎). 여유를 두고 넘으면 경고만.
MAX_KO_CHARS = 100
MAX_EN_WORDS = 40
# 시스템 프롬프트 v1.4b의 문장 수 규칙(두 문장, 조건이 갈릴 때만 세 문장). 서버 상한으로 잘리기 전 LLM 원답에 적용한다.
MAX_PROMPT_SENTENCES = 3

# 부서명: '…팀/처/센터/본부' + 조사. 검색결과에 없는 이름이면 지어낸 것으로 본다.
DEPT_NAME = re.compile(
    r"[가-힣]+?(?:팀|처|센터|본부)"
    r"(?=$|[\s,.!?]|에서|에|의|이나|나|과|와|를|을|은|는|으로|로|이|가|도)"
)
NOT_DEPTS = {"근처", "출처", "대처", "거처", "각처"}
DEFAULT_DEPTS = {"학사지원팀"}  # 근거가 없을 때 안내하도록 시스템 프롬프트가 지정한 곳


def sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?。])\s+", text.strip()) if s.strip()])


def raw_answer(calls) -> str:
    """서버 후처리(문장 수 상한) 전의 LLM 답변 — 마지막 answer 호출의 원문."""
    return next((c.get("text", "") for c in reversed(calls) if c["stage"] == "answer"), "")


def context_text(hits) -> str:
    """점검에 쓰는 이번 턴 검색결과 — 문서명·조항·본문 (부서명·조항 번호가 검색결과에 있었는지 확인용)."""
    return "\n".join(f"{h.source_name} {h.article} {h.text}" for h in hits)


def hangul_ratio(text: str) -> float:
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return hangul / (hangul + latin) if hangul + latin else 0.0


def check(case: dict, answer: str, path: str, calls=(), context: str = "") -> tuple[list[str], list[str]]:
    """(실패 사유, 경고) — 실패가 없으면 자동 점검 통과. context는 이번 턴 검색결과 본문."""
    issues, warns = [], []
    low = answer.lower()

    if any(c["stage"] == "answer" and c["stop_reason"] == "max_tokens" for c in calls):
        issues.append("답변 잘림 (출력 토큰 상한 도달)")

    exp_gate = case.get("expect_gate")
    if exp_gate == "block" and path != "gate_block":
        issues.append("게이트 차단 예상인데 통과함 → 프롬프트가 보류했는지 확인")
    if exp_gate == "pass" and path == "gate_block":
        issues.append("게이트에서 막힘 (검색 점수 미달 → LLM 미호출)")
    exp_path = case.get("expect_path")
    if exp_path and exp_path != path:
        issues.append(f"처리 경로 {path} (기대: {exp_path})")

    for s in case.get("must_include_all", []):
        if s.lower() not in low:
            issues.append(f"'{s}' 없음")
    for group in case.get("must_include_any", []):
        if not any(g.lower() in low for g in group):
            issues.append(f"[{' / '.join(group)}] 중 하나도 없음")
    for s in case.get("must_not_include", []):
        if s.lower() in low:
            issues.append(f"'{s}' 포함")
    for s in case.get("watch_for", []):
        if s.lower() in low:
            warns.append(f"'{s}' 언급 — 맥락 확인")

    if path in LLM_PATHS:
        if re.search(r"#\s*(Persona|페르소나)|</?persona>|<(검색결과|현재질문|대화기록)", answer, re.I):
            issues.append("프롬프트 내용이 답변에 섞임 (TTS가 그대로 읽음)")
        if "\n" in answer:
            issues.append("줄바꿈 포함 (음성 출력 규칙)")
        if re.search(r"\*\*|^#|^\s*[-•*]\s", answer, re.M):
            issues.append("마크다운·목록 기호")
        # '(점수: 0.87)'을 읽은 경우만 — '어학 기준 점수' 같은 일반 표현은 제외
        if re.search(r"점수\s*[:：]?\s*0?\.\d|\bscore\b\s*(?:of\s*)?0?\.\d", answer, re.I):
            issues.append("검색 점수를 읽음")
        if re.search(r"\d{4}\.\s?\d{1,2}\.\s?\d{1,2}\.", answer):
            issues.append("개정 날짜 표기를 읽음")
        if re.search(r"[()（）]", answer):
            issues.append("괄호 사용 (TTS가 괄호 안까지 그대로 읽음)")
        if re.search(r"[~∼〜]", answer):
            issues.append("물결표 사용 — 범위는 말로 (16학번부터 24학번까지)")
        raw = raw_answer(calls) or answer
        n = sentence_count(raw)
        if n > MAX_PROMPT_SENTENCES:
            cut = " — 서버 문장 상한이 줄여서 내보냄" if sentence_count(answer) < n else ""
            issues.append(f"LLM 원답 {n}문장 (프롬프트 기준 두 문장, 조건이 갈릴 때만 세 문장){cut}")
        if not case.get("greeting_ok") and re.match(r"\s*(안녕|hi\b|hello|hey)", answer, re.I):
            issues.append("묻지 않았는데 인사")
        want = case.get("answer_lang", case["lang"])
        ratio = hangul_ratio(answer)
        if want == "en" and ratio > 0.2:
            issues.append(f"영어로 답해야 하는데 한글 비율 {ratio:.0%}")
        if want == "ko" and ratio < 0.5:
            issues.append(f"한국어로 답해야 하는데 한글 비율 {ratio:.0%}")
        if want == "ko" and re.search(r"니다(?=[.!?,\s]|$)", answer):
            issues.append("합니다체 섞임 (해요체 규칙)")
        if want == "ko" and len(answer) > MAX_KO_CHARS:
            warns.append(f"음성 기준 긺 — {len(answer)}자 (기준 {MAX_KO_CHARS}자)")
        if want == "en" and len(answer.split()) > MAX_EN_WORDS:
            warns.append(f"음성 기준 긺 — {len(answer.split())}단어 (기준 {MAX_EN_WORDS}단어)")
        if path in SEARCH_PATHS:
            depts = {m.group(0) for m in DEPT_NAME.finditer(answer)} - NOT_DEPTS - DEFAULT_DEPTS
            for dept in sorted(d for d in depts if d not in context):
                issues.append(f"검색결과에 없는 부서명 '{dept}'")
            # '학칙 제50조에 따르면'처럼 검색결과에 없는 조항을 출처로 댄 경우 (10/27 음성 테스트)
            cited = {int(n) for n in re.findall(r"제\s?(\d+)\s?조", answer)}
            cited |= {int(n) for n in re.findall(r"\bArticle\s+(\d+)", answer, re.I)}
            compact = re.sub(r"\s+", "", context)
            for n in sorted(c for c in cited if f"제{c}조" not in compact):
                issues.append(f"검색결과에 없는 조항 '제{n}조'를 출처로 댐")
        if case.get("cites_source") and not re.search(
            r"학칙|규칙|규정|안내|에 따르면|according to|regulation|rules|guide", answer, re.I
        ):
            issues.append("근거 출처 표기 없음")
    return issues, warns


# ── 실행 ─────────────────────────────────────────────────────────

def run_case(case, client, trace, app, smalltalk, gate, dry_run: bool) -> dict:
    trace.reset()
    history = case.get("history", [])
    t = time.time()
    answer, error = "", None

    if dry_run:
        # LLM 없이 서버와 같은 순서로 잡담 판정 → 검색 → 게이트만 확인.
        # 꼬리질문 재작성은 LLM이 필요해 건너뛰고 원문으로 검색한다.
        if not smalltalk.is_smalltalk(case["question"]):
            hits = app.retriever.search(case["question"])
            gate.passes(hits)
        path = "smalltalk" if trace.smalltalk else ("gate_block" if trace.gate is False else "llm")
    else:
        messages = history + [{"role": "user", "content": case["question"]}]
        try:
            r = client.post("/v1/chat/completions", json={"messages": messages})
            r.raise_for_status()
            answer = r.json()["choices"][0]["message"]["content"]
        except Exception as e:  # 한 케이스 실패가 전체 실행을 멈추지 않게
            error = f"{type(e).__name__}: {e}"
        path = path_of(trace)

    seconds = round(time.time() - t, 2)
    context = context_text(trace.hits)
    issues, warns = ([], []) if dry_run else check(case, answer, path, trace.calls, context)
    if dry_run:
        if case.get("expect_gate") == "block" and path == "llm":
            issues.append("게이트 차단 예상인데 통과함")
        if case.get("expect_gate") == "pass" and path == "gate_block":
            issues.append("게이트에서 막힘 (검색 점수 미달)")
    if error:
        issues.insert(0, f"오류: {error}")

    return {
        "id": case["id"], "zone": case["zone"], "lang": case["lang"],
        "answer_lang": case.get("answer_lang", case["lang"]),
        "question": case["question"], "history": history,
        "basis": case.get("basis"), "expected": case.get("expected"),
        "path": path, "smalltalk": trace.smalltalk,
        "rewritten": trace.rewritten, "need_search": trace.need_search,
        "search_query": trace.search_query,
        "gate": trace.gate,
        "top_score": round(max((h.score for h in trace.hits), default=0.0), 3),
        "hits": [
            {"source": h.source_name, "article": h.article, "score": round(h.score, 3)}
            for h in trace.hits[:3]
        ],
        "answer": answer, "chars": len(answer), "words": len(answer.split()),
        "raw_answer": raw_answer(trace.calls),
        "error": error, "seconds": seconds,
        "llm_calls": trace.calls,
        "auto_pass": not issues, "issues": issues, "warnings": warns,
    }


def recheck(json_path: Path, cases: list[dict], retriever) -> tuple[dict, Path]:
    """저장된 결과에 현재 cases.json과 점검 규칙을 다시 적용한다 (LLM 호출 없음).

    부서명 점검에 필요한 검색결과 본문은 같은 질문으로 다시 검색해 복원한다(검색은 결정적).
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in cases}
    for r in data["results"]:
        case = by_id.get(r["id"])
        if case is None or data["meta"]["dry_run"]:
            continue
        context = ""
        if r["path"] in SEARCH_PATHS:
            query = r.get("search_query") or r.get("rewritten") or r["question"]
            context = context_text(retriever.search(query))
        issues, warns = check(case, r["answer"], r["path"], r["llm_calls"], context)
        if r.get("error"):
            issues.insert(0, f"오류: {r['error']}")
        r.update(basis=case.get("basis"), expected=case.get("expected"),
                 answer_lang=case.get("answer_lang", case["lang"]),
                 chars=len(r["answer"]), words=len(r["answer"].split()),
                 auto_pass=not issues, issues=issues, warnings=warns)
    data["meta"]["rechecked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data, json_path.with_suffix(".md")


def git_info() -> str:
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                                  text=True, encoding="utf-8").stdout.strip()
        except OSError:
            return ""
    commit = git("rev-parse", "--short", "HEAD") or "?"
    branch = git("branch", "--show-current") or "?"
    dirty = git("status", "--porcelain", "--", "prompts", "server")
    return f"{branch} @ {commit}" + (" (+ 커밋 안 된 프롬프트/서버 변경)" if dirty else "")


def prompt_version() -> str:
    head = (ROOT / "prompts" / "system_ko.md").read_text(encoding="utf-8")[:200]
    m = re.search(r"v\d+(?:\.\d+)*[a-z]?", head)  # v1.3, v1.4 (끝 알파벳 한 글자도 허용)
    return m.group(0) if m else "?"


def cost_usd(model: str, records: list[dict]) -> tuple[int, int, float | None]:
    tin = sum(c["input_tokens"] for r in records for c in r["llm_calls"])
    tout = sum(c["output_tokens"] for r in records for c in r["llm_calls"])
    price = PRICES.get(model)
    usd = (tin * price[0] + tout * price[1]) / 1_000_000 if price else None
    return tin, tout, usd


def md_cell(text: str, limit: int = 60) -> str:
    text = (text or "").replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_report(records, meta, out_md: Path):
    zones = []
    for r in records:
        if r["zone"] not in zones:
            zones.append(r["zone"])

    lines = [
        f"# 스모크 테스트 결과 — {meta['started']}",
        "",
        f"- 모델: `{meta['model']}` (effort `{meta['effort']}`)" if not meta["dry_run"]
        else "- 모드: **dry-run** (LLM 호출 없음 — 잡담 판정·검색·게이트만)",
        f"- 프롬프트: {meta['prompt_version']} · 코드: {meta['git']}",
        f"- 게이트 임계값: {meta['threshold']} · 케이스: {len(records)}개",
    ]
    if meta.get("rechecked"):
        lines.append(f"- 자동 점검 재적용: {meta['rechecked']} (답변은 원래 실행 그대로)")
    if not meta["dry_run"]:
        tin, tout, usd = meta["tokens_in"], meta["tokens_out"], meta["usd"]
        calls = sum(len(r["llm_calls"]) for r in records)
        cost = f"약 ${usd:.3f} (≈ {usd * KRW_PER_USD:,.0f}원, 환율 {KRW_PER_USD}원 가정)" if usd is not None else "단가 미등록 모델"
        lines.append(f"- LLM 호출 {calls}회 · 입력 {tin:,} / 출력 {tout:,} 토큰 · {cost}")
    lines += [
        "",
        "자동 점검은 형식·키워드 1차 필터입니다. **판정(O/X)은 아래 상세의 답변을 읽고 사람이 기록하세요.**",
        "",
        "## 구간별 요약",
        "",
        "| 구간 | 케이스 | 자동 점검 통과 | 게이트 통과 / 차단 | 평균 응답(s) |",
        "|---|---|---|---|---|",
    ]
    for z in zones:
        rs = [r for r in records if r["zone"] == z]
        passed = sum(r["auto_pass"] for r in rs)
        g_pass = sum(1 for r in rs if r["gate"] is True)
        g_block = sum(1 for r in rs if r["gate"] is False)
        avg = sum(r["seconds"] for r in rs) / len(rs)
        lines.append(f"| {z} | {len(rs)} | {passed}/{len(rs)} | {g_pass} / {g_block} | {avg:.1f} |")

    lines += [
        "",
        "## 케이스 목록",
        "",
        "| ID | 구간 | 질문 | 경로 | 최고점 | 길이 | 자동 점검 | 판정 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        auto = "통과" if r["auto_pass"] else f"실패 {len(r['issues'])}"
        if r["warnings"]:
            auto += f" · 경고 {len(r['warnings'])}"
        length = ""
        if r["answer"]:
            en = r.get("answer_lang", r["lang"]) == "en"
            length = f"{r['words']}단어" if en else f"{r['chars']}자"
        lines.append(
            f"| {r['id']} | {r['zone']} | {md_cell(r['question'], 40)} | {r['path']} "
            f"| {r['top_score']:.2f} | {length} | {auto} |  |"
        )

    lines += ["", "## 상세", ""]
    for r in records:
        lines += [f"### {r['id']} · {r['zone']} — {r['question']}", ""]
        for turn in r["history"]:
            who = "사용자" if turn["role"] == "user" else "치토"
            lines.append(f"- (대화기록) {who}: {turn['content']}")
        lines += [
            f"- 근거: {r['basis']}",
            f"- 기대: {r['expected']}",
        ]
        if r["rewritten"] and r["rewritten"] != r["question"]:
            lines.append(f"- 재작성된 질문: {r['rewritten']}")
        if r.get("search_query") and r["search_query"] != (r["rewritten"] or r["question"]):
            lines.append(f"- 검색용 한국어 질문: {r['search_query']}")
        if r["hits"]:
            hits = ", ".join(f"{h['source']} {h['article']} {h['score']:.2f}" for h in r["hits"])
            lines.append(f"- 검색 상위: {hits}")
        lines.append(f"- 경로: `{r['path']}` · {r['seconds']}s")
        if r["llm_calls"]:
            calls = ", ".join(
                f"{c['stage']} {c['input_tokens']}→{c['output_tokens']}tok {c['seconds']}s"
                for c in r["llm_calls"]
            )
            lines.append(f"- LLM: {calls}")
        if r["answer"]:
            lines += ["", f"> {r['answer']}", ""]
        raw = r.get("raw_answer") or ""
        if raw and raw.strip() != r["answer"].strip():
            lines += ["LLM 원답 (서버 문장 상한 적용 전):", "", f"> {raw}".replace("\n", " "), ""]
        for i in r["issues"]:
            lines.append(f"- ❌ {i}")
        for w in r["warnings"]:
            lines.append(f"- ⚠️ {w}")
        lines += ["", "판정: ☐ O ☐ X — 메모:", ""]

    out_md.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="AJOU-VIS 프롬프트 계약 스모크 테스트")
    ap.add_argument("--cases", default=str(HERE / "cases.json"))
    ap.add_argument("--dry-run", action="store_true",
                    help="LLM 호출 없이 잡담 판정·검색·게이트만 확인 (과금 없음)")
    ap.add_argument("--only", help="구간 또는 케이스 ID, 쉼표 구분 (예: A,C-gate,M1)")
    ap.add_argument("--model", help="LLM_MODEL 덮어쓰기 (예: claude-sonnet-5-5)")
    ap.add_argument("--effort", help="LLM_EFFORT 덮어쓰기 (low / medium / high)")
    ap.add_argument("--recheck", metavar="RESULT_JSON",
                    help="저장된 결과에 현재 점검 규칙·cases.json을 다시 적용 (LLM 호출 없음)")
    args = ap.parse_args()

    # server/.env보다 명령줄 값이 우선하도록 .env 로드 전에 설정 (load_dotenv는 덮어쓰지 않음)
    if args.model:
        os.environ["LLM_MODEL"] = args.model
    if args.effort:
        os.environ["LLM_EFFORT"] = args.effort

    sys.path.insert(0, str(SERVER))
    from dotenv import load_dotenv
    load_dotenv(SERVER / ".env")

    import app
    import gate
    import llm
    import rewriter
    import smalltalk
    from fastapi.testclient import TestClient

    if type(app.retriever).__name__ == "StubRetriever":
        sys.exit("corpus/chroma_db가 없습니다. 먼저 corpus/scripts/embed_corpus.py로 검색 DB를 만드세요.")

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.recheck:
        data, out_md = recheck(Path(args.recheck), cases, app.retriever)
        write_report(data["results"], data["meta"], out_md)
        passed = sum(r["auto_pass"] for r in data["results"])
        print(f"자동 점검 재적용: 통과 {passed}/{len(data['results'])}")
        for r in data["results"]:
            if r["issues"]:
                print(f"  XX {r['id']:<4} " + "; ".join(r["issues"]))
        print(f"결과: {out_md.resolve().relative_to(ROOT)}")
        return
    if args.only:
        wanted = {w.strip() for w in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted or c["zone"] in wanted]
        if not cases:
            sys.exit(f"--only {args.only}에 해당하는 케이스가 없습니다.")

    # 임베딩 모델(~10초)을 미리 올려 첫 케이스 응답 시간에 로딩이 섞이지 않게 한다 (/warmup과 동일)
    app.retriever.search("휴학", top_k=1)

    trace = Trace()
    install_tracing(app, gate, rewriter, smalltalk, llm, trace, with_llm=not args.dry_run)
    client = TestClient(app.app)

    started = datetime.now()
    model = "dry-run" if args.dry_run else llm.MODEL
    print(f"스모크 테스트 {len(cases)}개 · {model}" + ("" if args.dry_run else f" (effort {llm.EFFORT})"))
    records = []
    for case in cases:
        rec = run_case(case, client, trace, app, smalltalk, gate, args.dry_run)
        records.append(rec)
        mark = "OK " if rec["auto_pass"] else "XX "
        print(f"  {mark}{rec['id']:<4} {rec['zone']:<9} {rec['path']:<10} "
              f"top {rec['top_score']:.2f}  {rec['seconds']:>5.1f}s  "
              + ("; ".join(rec["issues"]) if rec["issues"] else ""))

    tin, tout, usd = cost_usd(model, records)
    meta = {
        "started": started.strftime("%Y-%m-%d %H:%M"),
        "model": model, "effort": None if args.dry_run else llm.EFFORT,
        "dry_run": args.dry_run, "threshold": gate.SCORE_THRESHOLD,
        "prompt_version": prompt_version(), "git": git_info(),
        "tokens_in": tin, "tokens_out": tout, "usd": usd,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    stem = f"smoke_{started.strftime('%Y%m%d-%H%M')}_{model}"
    (RESULTS / f"{stem}.json").write_text(
        json.dumps({"meta": meta, "results": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(records, meta, RESULTS / f"{stem}.md")

    passed = sum(r["auto_pass"] for r in records)
    print(f"\n자동 점검 통과 {passed}/{len(records)}")
    if not args.dry_run:
        print(f"토큰 입력 {tin:,} / 출력 {tout:,}" + (f" · 약 ${usd:.3f}" if usd is not None else ""))
    print(f"결과: {(RESULTS / f'{stem}.md').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
