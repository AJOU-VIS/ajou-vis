#!/usr/bin/env python3
"""학습형 게이트의 이득이 '발화 길이' 같은 데이터 생성 습관에서 온 것은 아닌지 확인한다 (새 데이터·API 불필요).

LLM이 만든 꼬리질문은 짧고 독립 질문은 긴 경향이 있다. 분류기가 '짧으면 재작성'을 배웠다면, 실제 사용(짧은 독립 질문)에서는
이득이 사라진다. 그래서 (1) 길이 분포 (2) 특징을 바꿔 가며 같은 재현율의 생략률 (3) 길이를 맞춘 구간별 AUC (4) 시험 세트 확인을 본다.

실행 (저장소 루트):
  server/.venv/bin/python eval/gate_learn/ablation.py
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_lib as L  # noqa: E402
import train_eval as T  # noqa: E402

SCORE = ["top1", "top2", "margin", "mean3"]
SUBSETS = [
    ("전체 특징 (보고서의 LR)", list(L.FEATURES)),
    ("길이 특징 제외 (len, tokens)", [f for f in L.FEATURES if f not in ("len", "tokens")]),
    ("검색 점수 특징만", SCORE),
    ("검색 점수 + 길이", SCORE + ["len"]),
    ("길이만 (len)", ["len"]),
]


def f(x):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else "%.0f%%" % (100 * x)


def run(rows, out_dir, log=print):
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import GroupKFold
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        raise SystemExit("scikit-learn이 필요합니다: server/.venv/bin/pip install scikit-learn")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pool = [r for r in rows if not r["external"] and not r["signal"] and r["label"] in (0, 1)]
    ext = [r for r in rows if r["external"] and not r["signal"]]
    y = np.array([r["label"] for r in pool])
    g = np.array([r["call"] for r in pool])
    mat = lambda rs, fs: np.array([[r[c] for c in fs] for r in rs])
    mk = lambda: make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced"))
    n_splits = min(5, len(set(g)))

    def oof(fs):
        X, p = mat(pool, fs), np.zeros(len(y))
        for tr, te in GroupKFold(n_splits=n_splits).split(X, y, g):
            p[te] = mk().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
        return p

    def external(fs, p_oof):
        """교차검증에서 재현율 98%가 되는 기준을 정해, 직접 만든 시험 세트에 적용한다."""
        if not ext:
            return None
        th = L.skip_at_recall(p_oof, y, 0.98)[1]
        pe = mk().fit(mat(pool, fs), y).predict_proba(mat(ext, fs))[:, 1]
        ye = [r["label"] for r in ext]
        miss = sum(1 for p, t in zip(pe, ye) if t == 1 and p < th)
        neg = [p for p, t in zip(pe, ye) if t == 0]
        return miss, sum(1 for t in ye if t == 1), sum(1 for p in neg if p < th), len(neg)

    lens = np.array([r["len"] for r in pool])
    lines = ["# 길이 의존 점검 (학습형 게이트)", "",
             "학습·평가 샘플 %d개 (재작성 필요 %d · 건너뛰어도 됨 %d), 시험 세트 %d개" % (len(y), int(y.sum()), int((1 - y).sum()), len(ext)), "",
             "## 1) 발화 길이 분포 (글자 수, 공백 제외)", "", "| | 재작성 필요 | 건너뛰어도 됨 |", "|---|---|---|"]
    pc = lambda a: "%d (%d~%d)" % tuple(np.percentile(a, [50, 25, 75]))
    lines.append("| 중앙값 (25%%~75%%) | %s | %s |" % (pc(lens[y == 1]), pc(lens[y == 0])))
    a_len = L.auc((-lens).tolist(), y.tolist())
    lines += ["", "- **길이만으로** '재작성 필요'를 가린 AUC: **%.3f** (0.5=우연, 검색 점수 규칙은 %.3f)" % (
        a_len, L.auc((1 - mat(pool, ["top1"])[:, 0]).tolist(), y.tolist())), ""]

    s_rule = 1.0 - mat(pool, ["top1"])[:, 0]
    th_rule = L.skip_at_recall(s_rule, y, 0.98)[1]
    res = {"규칙(검색 점수)": (s_rule, ["top1"])}
    preds = {}
    for name, fs in SUBSETS:
        preds[name] = oof(fs)
        res[name] = (preds[name], fs)

    lines += ["## 2) 특징을 바꿔 가며 (교차검증, 같은 재현율에서의 생략률)", "",
              "| 특징 | AUC | 재현율 95%에서 생략 | 재현율 98%에서 생략 | 시험 세트: 꼬리질문 놓침 | 시험 세트: 독립 질문 건너뜀 |", "|---|---|---|---|---|---|"]
    summary = {}
    for name, (s, fs) in res.items():
        ex = None
        if ext:
            if name.startswith("규칙"):
                re_ = 1.0 - mat(ext, ["top1"])[:, 0]
                ye = [r["label"] for r in ext]
                ex = (sum(1 for p, t in zip(re_, ye) if t == 1 and p < th_rule), sum(1 for t in ye if t == 1),
                      sum(1 for p, t in zip(re_, ye) if t == 0 and p < th_rule), sum(1 for t in ye if t == 0))
            else:
                ex = external(fs, s)
        s95, s98 = L.skip_at_recall(s, y, 0.95)[0], L.skip_at_recall(s, y, 0.98)[0]
        a = L.auc(list(s), y.tolist())
        summary[name] = {"auc": a, "skip95": s95, "skip98": s98, "ext": ex}
        lines.append("| %s | %.3f | %s | %s | %s | %s |" % (
            name, a, f(s95), f(s98), ("%d/%d" % ex[:2]) if ex else "-", ("%d/%d (%s)" % (ex[2], ex[3], f(ex[2] / max(1, ex[3])))) if ex else "-"))

    # 길이를 맞춘 구간별 AUC
    edges = np.percentile(lens, [100 / 3.0, 200 / 3.0])
    bins = [("짧음", lens <= edges[0]), ("중간", (lens > edges[0]) & (lens <= edges[1])), ("긴 편", lens > edges[1])]
    all_name, no_len = SUBSETS[0][0], SUBSETS[1][0]
    lines += ["", "## 3) 길이를 맞춰 본 비교 (발화 길이 3등분, 구간 안의 AUC)", "",
              "| 길이 구간 | 길이(글자) | 샘플 (필요/불필요) | 규칙 AUC | LR 전체 AUC | LR 길이 제외 AUC |", "|---|---|---|---|---|---|"]
    for nm, mask in bins:
        yy = y[mask]
        lo, hi = (int(lens[mask].min()), int(lens[mask].max())) if mask.any() else (0, 0)
        if mask.sum() < 10 or yy.sum() == 0 or yy.sum() == len(yy):
            lines.append("| %s | %d~%d | %d/%d | - | - | - |" % (nm, lo, hi, int(yy.sum()), int((1 - yy).sum())))
            continue
        au = lambda s: L.auc(list(np.asarray(s)[mask]), yy.tolist())
        lines.append("| %s | %d~%d | %d/%d | %.3f | %.3f | %.3f |" % (nm, lo, hi, int(yy.sum()), int((1 - yy).sum()), au(s_rule), au(preds[all_name]), au(preds[no_len])))

    lines += ["", "## 읽는 법", "",
              "- **'길이 특징 제외' 행의 이득이 '전체'와 비슷하게 남으면**: 이득은 길이 때문이 아니다. 신뢰도가 올라간다.",
              "- **'길이 제외'에서 규칙과의 차이가 크게 줄면**: 이득의 상당 부분은 생성 습관(짧은 꼬리질문, 긴 독립 질문)이다. 데이터를 길이가 섞이게 다시 만들어야 한다.",
              "- **'길이만' AUC가 높으면**(예: 0.8 이상): 길이가 라벨과 강하게 얽혀 있다는 뜻이다. 실제 사용에서는 얽힘이 약할 가능성이 크다.",
              "- **3) 구간별 AUC**에서 같은 길이 안에서도 LR이 규칙보다 높으면 이득이 길이만으로 설명되지 않는다.",
              "- 시험 세트의 꼬리질문은 3개뿐이라 참고용이다."]
    text = "\n".join(lines)
    (out_dir / "ablation.md").write_text(text, encoding="utf-8")
    log(text)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=str(HERE / "data" / "features.csv"))
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--label", choices=["auto", "real", "oracle"], default="auto")
    a = ap.parse_args()
    run(T.load_rows(a.features, a.label), a.out)
    print("\n저장: %s/ablation.md" % a.out)


if __name__ == "__main__":
    main()
