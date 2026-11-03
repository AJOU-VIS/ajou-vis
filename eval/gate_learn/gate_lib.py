"""학습형 재작성 게이트 타당성 시험 — 공용 함수 (생성 · 라벨/특징 · 평가).

전체 흐름
  gen_data.py       코퍼스 두 주제(A, B)로 LLM이 (이전 대화, 꼬리질문, 독립 질문) 샘플을 만든다 (Claude 호출, 비용 발생)
  build_features.py 각 샘플을 검색해서 라벨과 특징을 계산한다 (LLM 호출 없음)
  train_eval.py     작은 분류기를 학습하고, 지금 규칙(검색 점수 기준)과 같은 재현율에서 생략률을 비교한다

라벨 정의 (재작성 없이 검색했을 때 정답 문서가 LLM에 들어가는가)
  raw_hit  = 발화 그대로 검색한 상위 K개(기본 5, 서버가 LLM에 넘기는 개수)에 정답 문서가 있다
  full_hit = 독립 질문으로 풀어 쓴 문장(full_question)으로 검색한 상위 K개에 정답 문서가 있다
  label 0 (건너뛰어도 됨)  : raw_hit
  label 1 (재작성이 도움됨): raw_hit이 아니고 full_hit
  label -1 (모호, 학습에서 제외): 둘 다 아님 — 재작성해도 못 찾는 검색기 한계라 게이트의 몫이 아니다

파이썬 3.9에서도 돌아가도록 쓴다(타입 힌트는 문자열로만 평가).
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
import rewrite_gate  # noqa: E402  (신호 규칙과 일반어 목록을 그대로 쓴다)

RAW = ROOT / "corpus" / "raw"
FEATURES = ["top1", "top2", "margin", "mean3", "len", "tokens", "generic_ratio", "has_digit",
            "prev_overlap", "prev_top1_match", "cos_q", "cos_a", "lex_overlap"]


# ───────────────────────── 1) 코퍼스 단위와 생성 ─────────────────────────

STUDENT_WORDS = ["학생", "학점", "등록", "장학", "성적", "졸업", "휴학", "복학", "수업", "입학", "전과", "제적", "징계", "수강", "학위",
                 "편입", "재입학", "유급", "자퇴", "학기", "교과", "수료", "학사", "시험", "평점", "외국인", "기숙", "휴업"]


def strip_revisions(text: str) -> str:
    """규정 본문의 개정·삭제 표시(<개정 2007.7.25.> 등)와, 내용이 지워져 번호만 남은 항을 없앤다."""
    t = re.sub(r"<(신설|개정|삭제|전문개정)[^>]*>", "", text)
    t = re.sub(r"[①-⑮]\s*(?=[①-⑮]|$)", "", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def load_units(min_chars: int = 120, raw_dir=None, student_only: bool = True):
    """규정 조항과 학사 안내 섹션을 '주제 단위'로 읽는다. article은 검색 결과의 article과 같은 형식으로 맞춘다."""
    raw = Path(raw_dir) if raw_dir else RAW
    units = []
    for p in sorted(raw.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(d, dict) and "articles" in d and p.name[:3].isdigit():
            for a in d["articles"]:
                art = "%s(%s)" % (a["article_no"], a["article_title"]) if a.get("article_no") else a.get("article_title", "")
                units.append({"source": d["rule_name"], "article": art, "text": strip_revisions(a["text"]), "kind": "규정"})
        elif isinstance(d, dict) and "sections" in d and p.name.startswith("academic_"):
            for s in d["sections"]:
                units.append({"source": d["source_name"], "article": s["title"], "text": strip_revisions(s["text"]), "kind": "안내"})
    units = [u for u in units if len(u["text"]) >= min_chars]
    if student_only:   # 학생이 묻지 않는 운영·조직 조항(대학이념, 기구, 교무회의 등)은 뺀다. 안내 페이지는 모두 학생용이다.
        units = [u for u in units if u["kind"] != "규정" or any(w in u["article"] + " " + u["text"] for w in STUDENT_WORDS)]
    for u in units:
        u["uid"] = u["source"] + "|" + u["article"]
    # 정답 키(출처|조항)가 같은 단위는 하나만 남긴다(더 긴 쪽). 호출들이 같은 정답 문서를 공유하면 교차검증에 누출이 생긴다.
    best = {}
    for u in units:
        if u["uid"] not in best or len(u["text"]) > len(best[u["uid"]]["text"]):
            best[u["uid"]] = u
    return list(best.values())


def make_pairs(units, n: int, seed: int):
    """서로 다른 문서(source)의 단위를 짝짓는다. 한 단위는 한 번만 쓴다(같은 주제가 여러 호출에 퍼지지 않게)."""
    rng = random.Random(seed)
    pool = list(units)
    rng.shuffle(pool)
    pairs = []
    while len(pairs) < n and len(pool) >= 2:
        a = pool.pop()
        j = next((k for k, u in enumerate(pool) if u["source"] != a["source"]), None)
        if j is None:
            break
        pairs.append((a, pool.pop(j)))
    return pairs


SYSTEM_PROMPT = ("당신은 아주대학교 음성 비서 '치토'의 평가 데이터를 만드는 도우미입니다. "
                 "설명 없이 JSON 한 개만 출력하세요. 코드 블록 표시(```)도 쓰지 마세요.")


def build_prompt(a, b):
    """주제 A(이전 대화·꼬리질문)와 주제 B(독립 질문)로 한 번에 만든다."""
    user = (
        "아래 두 문서 조각으로 학생과 치토의 대화 데이터를 만드세요.\n\n"
        "[주제 A] 출처: %s / %s\n%s\n\n"
        "[주제 B] 출처: %s / %s\n%s\n\n"
        "만들 것 (모두 음성으로 말하듯 자연스러운 한국어, 학생은 반말 또는 요체):\n"
        "1) history: 주제 A에 대한 학생 질문 1개(user)와, 문서 내용에 근거한 치토의 해요체 답변 1~2문장(assistant)\n"
        "2) followups: 방금 대화를 이어서 주제 A에 대해 묻는 짧은 학생 발화 4개. 앞 대화를 모르면 무엇에 대한 질문인지 알 수 없어야 한다.\n"
        "   - '그럼', '그건', '그거', '거기', '아까', '방금' 같은 지시어·접속어는 쓰지 않는다. 주제 A의 이름(예: 휴학, 전과, 졸업)도 넣지 않는다.\n"
        "   - 1개는 type=\"elliptical\": 명사 없이 질문 단어만으로 된 짧은 발화 (예: \"신청 기간은 언제까지야?\").\n"
        "   - 3개는 type=\"ambiguous\": 주제 A와 관련된 대상·항목을 가리키는 명사를 하나 넣되, 앞 대화가 없으면 어떤 제도나 절차의 이야기인지 알 수 없게 쓴다\n"
        "     (예: 전과 이야기 뒤의 \"장학금은 어떻게 돼?\", 증명서 이야기 뒤의 \"졸업생은?\", 휴학 이야기 뒤의 \"군대는?\"). 이 명사만 보면 다른 제도의 질문으로 오해할 수 있는 것이 좋다. 3개는 서로 다른 명사를 쓴다.\n"
        "   - 서로 다른 측면을 묻는다. 각 발화마다 full_question(주제 A를 분명히 밝혀 혼자서도 뜻이 통하게 다시 쓴 질문, ambiguous는 그 명사를 유지)을 함께 쓴다.\n"
        "3) standalone: 앞 대화와 상관없이 주제 B에 대한 완결된 학생 질문 3개. 주제 B의 핵심 명사를 넣고 서로 다른 측면을 묻는다.\n\n"
        "출력 형식:\n"
        "{\"history\": {\"user\": \"...\", \"assistant\": \"...\"},\n"
        " \"followups\": [{\"utterance\": \"...\", \"full_question\": \"...\", \"type\": \"elliptical\"}, ...],\n"
        " \"standalone\": [{\"utterance\": \"...\"}, ...]}"
    ) % (a["source"], a["article"], a["text"][:900], b["source"], b["article"], b["text"][:900])
    return SYSTEM_PROMPT, user


def parse_generation(text: str):
    """LLM 응답에서 JSON을 꺼내 형식을 검사한다. 잘못되면 None."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        h = d["history"]
        if not (isinstance(h.get("user"), str) and isinstance(h.get("assistant"), str) and h["user"].strip() and h["assistant"].strip()):
            return None
        fol = [f for f in d.get("followups", []) if isinstance(f, dict) and isinstance(f.get("utterance"), str)
               and isinstance(f.get("full_question"), str) and f["utterance"].strip() and f["full_question"].strip()]
        sta = [s for s in d.get("standalone", []) if isinstance(s, dict) and isinstance(s.get("utterance"), str) and s["utterance"].strip()]
        if not fol and not sta:
            return None
        return {"history": h, "followups": fol, "standalone": sta}
    except (ValueError, KeyError, AttributeError, TypeError):
        return None


def to_samples(call_id: int, a, b, gen):
    """생성 결과를 평가 샘플로 바꾼다. 꼬리질문의 정답은 주제 A, 독립 질문의 정답은 주제 B."""
    hist = [{"role": "user", "content": gen["history"]["user"].strip()},
            {"role": "assistant", "content": gen["history"]["assistant"].strip()}]
    out = []
    for k, f in enumerate(gen["followups"]):
        out.append({"id": "c%03d-f%d" % (call_id, k), "call": call_id, "type": "followup", "difficulty": f.get("type", ""),
                    "history": hist, "utterance": f["utterance"].strip(), "full_question": f["full_question"].strip(),
                    "gold_source": a["source"], "gold_article": a["article"]})
    for k, s in enumerate(gen["standalone"]):
        u = s["utterance"].strip()
        out.append({"id": "c%03d-s%d" % (call_id, k), "call": call_id, "type": "standalone", "difficulty": "",
                    "history": hist, "utterance": u, "full_question": u,
                    "gold_source": b["source"], "gold_article": b["article"]})
    return out


# ───────────────────────── 2) 라벨과 특징 ─────────────────────────

def hit(hits, source: str, article: str, k: int = 5, strict: bool = True) -> bool:
    for h in list(hits)[:k]:
        if h.source_name == source and (not strict or h.article == article):
            return True
    return False


def _tokens(text: str):
    return [t for t in re.split(r"[\s,?!.]+", text.strip()) if t]


def _stem(tok: str) -> str:
    return rewrite_gate._PARTICLES.sub("", tok)


def _cos(u, v) -> float:
    return float(sum(x * y for x, y in zip(u, v)))  # 임베딩은 정규화되어 있다고 가정


def compute_row(sample, search, embed, k: int = 5):
    """한 샘플의 라벨과 특징을 만든다. search(text)는 SearchHit 목록, embed(list[str])는 정규화된 벡터 목록."""
    utt, full = sample["utterance"], sample["full_question"]
    prev_q = next(m["content"] for m in sample["history"] if m["role"] == "user")
    prev_a = next((m["content"] for m in sample["history"] if m["role"] == "assistant"), "")
    raw = search(utt)
    full_hits = search(full) if full != utt else raw
    prev = search(prev_q)
    gs, ga = sample.get("gold_source"), sample.get("gold_article")
    row = {"id": sample["id"], "call": sample.get("call", -1), "type": sample["type"], "difficulty": sample.get("difficulty", ""),
           "utterance": utt, "full_question": full, "prev_question": prev_q, "external": int(bool(sample.get("external")))}
    row["signal"] = int(rewrite_gate.followup_signal(utt) is not None)   # 1이면 지금 규칙이 이미 재작성으로 보내는 발화
    row["gold"] = ("%s|%s" % (gs, ga)) if gs is not None else ""
    row["raw_top3"] = " / ".join("%s|%s" % (h.source_name, h.article) for h in list(raw)[:3])
    if gs is not None:
        rh, fh = hit(raw, gs, ga, k), hit(full_hits, gs, ga, k)
        row["raw_hit"], row["full_hit"] = int(rh), int(fh)
        row["raw_hit_page"] = int(hit(raw, gs, ga, k, strict=False))
        row["label"] = 0 if rh else (1 if fh else -1)
    else:                                   # 직접 만든 시험 세트: 정답 문서가 없으니 종류로 라벨을 준다
        row["raw_hit"] = row["full_hit"] = row["raw_hit_page"] = -1
        row["label"] = 1 if sample["type"] == "followup" else 0
    sc = [h.score for h in raw] + [0.0, 0.0, 0.0]
    toks = _tokens(utt)
    stems = [_stem(t) for t in toks]
    generic = sum(1 for s in stems if (not s) or len(s) <= 1 or s in rewrite_gate.GENERIC)
    prev_src = [h.source_name for h in prev[:3]]
    raw_src = [h.source_name for h in raw[:3]]
    content = [s for s in stems if len(s) >= 2 and s not in rewrite_gate.GENERIC]
    ctx = prev_q + " " + prev_a
    vecs = embed([utt, prev_q, prev_a])
    row.update({
        "top1": sc[0], "top2": sc[1], "margin": sc[0] - sc[1], "mean3": sum(sc[:3]) / 3.0,
        "len": len(re.sub(r"\s", "", utt)), "tokens": len(toks),
        "generic_ratio": generic / max(1, len(toks)), "has_digit": int(bool(re.search(r"\d", utt))),
        "prev_overlap": len(set(raw_src) & set(prev_src)) / 3.0,
        "prev_top1_match": int(bool(raw and prev and raw[0].source_name == prev[0].source_name)),
        "cos_q": _cos(vecs[0], vecs[1]), "cos_a": _cos(vecs[0], vecs[2]),
        "lex_overlap": (sum(1 for s in content if s in ctx) / len(content)) if content else 0.0,
    })
    return row


# ───────────────────────── 3) 평가: 같은 재현율에서 생략률 ─────────────────────────

def skip_at_recall(s, y, target: float):
    """s가 클수록 '재작성'. 재작성 필요(y=1) 중 target 이상을 재작성으로 보내는 가장 높은 기준 θ를 고르고,
    그때 건너뛴 비율(y=0 중 s<θ)을 돌려준다. (skip_rate, θ, 실제 재현율)"""
    pos = sorted((v for v, t in zip(s, y) if t == 1), reverse=True)
    neg = [v for v, t in zip(s, y) if t == 0]
    if not pos or not neg:
        return float("nan"), float("nan"), float("nan")
    kk = max(1, int(math.ceil(target * len(pos) - 1e-9)))
    theta = pos[kk - 1]
    recall = sum(1 for v in pos if v >= theta) / len(pos)
    skip = sum(1 for v in neg if v < theta) / len(neg)
    return skip, theta, recall


def auc(s, y) -> float:
    pos = [v for v, t in zip(s, y) if t == 1]
    neg = [v for v, t in zip(s, y) if t == 0]
    if not pos or not neg:
        return float("nan")
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def group_bootstrap_diff(s_a, s_b, y, groups, target: float, n_boot: int = 300, seed: int = 11):
    """묶음(호출) 단위로 다시 뽑아 skip_at_recall(a) − skip_at_recall(b)의 95% 구간을 구한다."""
    rng = random.Random(seed)
    by = {}
    for i, g in enumerate(groups):
        by.setdefault(g, []).append(i)
    keys = list(by)
    diffs = []
    for _ in range(n_boot):
        idx = [i for g in (rng.choice(keys) for _ in keys) for i in by[g]]
        a = skip_at_recall([s_a[i] for i in idx], [y[i] for i in idx], target)[0]
        b = skip_at_recall([s_b[i] for i in idx], [y[i] for i in idx], target)[0]
        if not (math.isnan(a) or math.isnan(b)):
            diffs.append(a - b)
    diffs.sort()
    if not diffs:
        return float("nan"), float("nan")
    return diffs[int(0.025 * len(diffs))], diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))]
