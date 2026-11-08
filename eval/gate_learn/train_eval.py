#!/usr/bin/env python3
"""3단계: 작은 분류기를 학습하고, 지금 규칙(검색 점수가 기준 미만이면 재작성)과 '같은 재현율에서 생략률'을 비교한다.

재현율 = 재작성이 필요한 발화 중 실제로 재작성으로 보낸 비율 (놓치면 맥락 없이 검색해 오답 위험)
생략률 = 재작성이 필요 없는 발화 중 건너뛴 비율 (높을수록 시간이 준다)
평가는 '같은 호출에서 나온 샘플은 한쪽에만' 들어가게 묶어서 5겹 교차검증한 예측(OOF)으로 한다. 새 주제에서도 되는지 보려는 것이다.
직접 만든 시험 세트 40개는 학습에 쓰지 않고 마지막에 외부 확인으로만 쓴다.

실행 (저장소 루트, scikit-learn 필요: server/.venv/bin/pip install scikit-learn):
  server/.venv/bin/python eval/gate_learn/train_eval.py
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_lib as L  # noqa: E402

TARGETS = (0.90, 0.95, 0.98, 1.00)
INT_COLS = ("call", "external", "signal", "label", "label_oracle", "label_real", "raw_hit", "full_hit", "real_hit", "raw_hit_page")


def load_rows(path, label: str = "auto"):
    """label: auto=저장된 label 열(실제 재작성기로 계산했으면 real), real/oracle=해당 라벨 열을 쓴다."""
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        for c in L.FEATURES:
            r[c] = float(r[c])
        for c in INT_COLS:
            r[c] = int(float(r[c]))
        if label in ("real", "oracle") and not r["external"]:
            r["label"] = r["label_" + label]
            if r["label"] == -9:
                raise SystemExit("label_real이 없습니다. build_features.py를 --rewrite real로 실행하세요.")
        rows.append(r)
    return rows


def pct(x):
    return "-" if (x is None or (isinstance(x, float) and math.isnan(x))) else "%.0f%%" % (100 * x)


def run(rows, out_dir, n_splits: int = 5, seed: int = 0, population: str = "nosignal", log=print):
    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import GroupKFold
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        raise SystemExit("scikit-learn이 필요합니다: server/.venv/bin/pip install scikit-learn")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pool = [r for r in rows if not r["external"] and (population == "all" or not r["signal"])]
    internal = [r for r in pool if r["label"] in (0, 1)]
    ambiguous = sum(1 for r in pool if r["label"] == -1)
    external = [r for r in rows if r["external"] and (population == "all" or not r["signal"])]
    log("대상: %s" % ("전체 발화" if population == "all" else "신호 없는 발화 (지금 규칙의 신호가 잡지 못하는 것)"))
    X = np.array([[r[f] for f in L.FEATURES] for r in internal])
    y = np.array([r["label"] for r in internal])
    g = np.array([r["call"] for r in internal])
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    if n_pos < 20 or n_neg < 20:
        raise SystemExit("학습할 샘플이 너무 적습니다 (재작성 필요 %d · 불필요 %d). 샘플을 더 만드세요." % (n_pos, n_neg))
    log("학습·평가 샘플 %d개: 재작성 필요 %d · 건너뛰어도 됨 %d · 모호로 제외 %d · 묶음(호출) %d개" % (len(y), n_pos, n_neg, ambiguous, len(set(g))))

    def make_models():
        return {
            "LR": make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")),
            "GB": GradientBoostingClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=seed),
        }

    # 묶음 교차검증으로 샘플별 예측(OOF)을 만든다
    oof = {name: np.zeros(len(y)) for name in make_models()}
    k = min(n_splits, len(set(g)))
    for tr, te in GroupKFold(n_splits=k).split(X, y, g):
        for name, m in make_models().items():
            m.fit(X[tr], y[tr])
            oof[name][te] = m.predict_proba(X[te])[:, 1]
    s_rule = 1.0 - X[:, L.FEATURES.index("top1")]            # 지금 규칙: 검색 점수가 낮을수록 재작성
    scores = {"규칙(검색 점수)": s_rule, "LR": oof["LR"], "GB": oof["GB"]}

    lines = ["# 학습형 게이트 타당성 시험 결과 (대상: %s)" % ("전체 발화" if population == "all" else "신호 없는 발화"), "",
             "- 학습·평가 샘플 %d개 (재작성 필요 %d · 건너뛰어도 됨 %d), 모호로 제외 %d, 호출 묶음 %d개, %d겹 묶음 교차검증" % (len(y), n_pos, n_neg, ambiguous, len(set(g)), k),
             "- 대상은 신호(그럼·거기·영어로 등)가 없는 발화뿐이다. 재현율 = 재작성이 필요한 발화 중 재작성으로 보낸 비율, 생략률 = 필요 없는 발화 중 건너뛴 비율", "",
             "## 같은 재현율에서의 생략률 (교차검증 예측)", "",
             "| 재현율 목표 | " + " | ".join(scores) + " | LR − 규칙 (95% 구간) |", "|---|" + "---|" * (len(scores) + 1)]
    table = {}
    for t in TARGETS:
        cells, vals = [], {}
        for name, s in scores.items():
            sk, th, rc = L.skip_at_recall(s, y, t)
            vals[name] = sk
            cells.append("%s (실제 재현율 %s)" % (pct(sk), pct(rc)))
        ci = "-"
        if t in (0.95, 0.98):
            lo, hi = L.group_bootstrap_diff(scores["LR"], s_rule, y.tolist(), g.tolist(), t)
            ci = "%+.0f%%p [%+.0f, %+.0f]" % (100 * (vals["LR"] - vals["규칙(검색 점수)"]), 100 * lo, 100 * hi)
        elif t == 1.0:
            ci = "%+.0f%%p (구간 생략: 표본이 너무 작아 불안정)" % (100 * (vals["LR"] - vals["규칙(검색 점수)"]))
        else:
            ci = "%+.0f%%p" % (100 * (vals["LR"] - vals["규칙(검색 점수)"]))
        table[t] = vals
        lines.append("| %d%% | " % (100 * t) + " | ".join(cells) + " | " + ci + " |")
    lines += ["", "AUC (재작성 필요를 가려내는 정도, 0.5=우연, 1.0=완벽): " + " · ".join("%s %.3f" % (n, L.auc(s, y)) for n, s in scores.items()), ""]

    # 최종 모델: 전체로 학습, 계수 확인, 외부 확인
    final = make_models()
    for m in final.values():
        m.fit(X, y)
    coefs = final["LR"].named_steps["logisticregression"].coef_[0]
    order = sorted(range(len(L.FEATURES)), key=lambda i: -abs(coefs[i]))
    lines += ["## LR 계수 (표준화된 특징, 양수일수록 '재작성 필요' 쪽)", "", "| 특징 | 계수 |", "|---|---|"]
    lines += ["| %s | %+.2f |" % (L.FEATURES[i], coefs[i]) for i in order]

    summary = {"n": len(y), "pos": n_pos, "neg": n_neg, "ambiguous": ambiguous, "table": table,
               "auc": {n: L.auc(s, y) for n, s in scores.items()}}
    if external:
        Xe = np.array([[r[f] for f in L.FEATURES] for r in external])
        ye = np.array([r["label"] for r in external])
        _, th_lr, _ = L.skip_at_recall(oof["LR"], y, 0.98)
        _, th_rule, _ = L.skip_at_recall(s_rule, y, 0.98)
        p_e = final["LR"].predict_proba(Xe)[:, 1]
        rule_e = 1.0 - Xe[:, L.FEATURES.index("top1")]
        lines += ["", "## 외부 확인: 직접 만든 시험 세트 (학습에 쓰지 않음, 재현율 98% 기준 지점)", "",
                  "- 재현율 98%% 기준 지점은 교차검증 예측에서 정했다 (LR 기준 확률 %.2f 이상이면 재작성, 규칙 기준 점수 %.2f 미만이면 재작성)" % (th_lr, 1 - th_rule), "",
                  "| 시험 세트 항목 | 종류 | 검색 점수 | LR 확률 | 규칙 결정 | LR 결정 |", "|---|---|---|---|---|---|"]
        miss = {"규칙": 0, "LR": 0}
        for r, p, rs, yy in zip(external, p_e, rule_e, ye):
            d_rule = "재작성" if rs >= th_rule else "건너뜀"
            d_lr = "재작성" if p >= th_lr else "건너뜀"
            if yy == 1:
                miss["규칙"] += d_rule == "건너뜀"
                miss["LR"] += d_lr == "건너뜀"
            lines.append("| %s | %s | %.2f | %.2f | %s | %s |" % (r["id"], "꼬리질문" if yy else "독립", 1 - rs, p, d_rule, d_lr))
        sk_rule = sum(1 for rs, yy in zip(rule_e, ye) if yy == 0 and rs < th_rule) / max(1, int((ye == 0).sum()))
        sk_lr = sum(1 for p, yy in zip(p_e, ye) if yy == 0 and p < th_lr) / max(1, int((ye == 0).sum()))
        lines += ["", "- 꼬리질문 %d개 중 건너뛴(놓친) 개수: 규칙 %d · LR %d  /  독립 질문 %d개 중 건너뛴 비율: 규칙 %s · LR %s" % (
            int((ye == 1).sum()), miss["규칙"], miss["LR"], int((ye == 0).sum()), pct(sk_rule), pct(sk_lr))]
        summary["external"] = {"miss_rule": miss["규칙"], "miss_lr": miss["LR"], "skip_rule": sk_rule, "skip_lr": sk_lr}

    lines += ["", "## 읽을 때 주의", "",
              "- 데이터는 LLM이 만든 것이라 실제 사용자 발화보다 쉽거나 어색할 수 있다. 라벨이 맞는지 `review.csv`를 직접 훑어서 확인해야 한다.",
              "- 라벨은 '발화 그대로 검색한 상위 K개에 정답 문서가 들어가는가'라는 검색 기준이다. 정답 문서에 들어가도 답이 틀릴 수 있다.",
              "- 같은 재현율에서의 비교라 규칙과 분류기가 같은 조건이다. 표본이 작으면 재현율 100% 지점은 불안정하다."]
    text = "\n".join(lines)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    with (out_dir / "oof_predictions.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "call", "type", "label", "top1", "p_lr", "p_gb", "utterance"])
        for r, a, b in zip(internal, oof["LR"], oof["GB"]):
            w.writerow([r["id"], r["call"], r["type"], r["label"], "%.3f" % r["top1"], "%.3f" % a, "%.3f" % b, r["utterance"]])
    log(text)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=str(HERE / "data" / "features.csv"))
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--label", choices=["auto", "real", "oracle"], default="auto", help="라벨 기준 (auto: 저장된 기본 라벨)")
    ap.add_argument("--population", choices=["nosignal", "all"], default="nosignal",
                    help="nosignal: 지금 규칙의 신호가 없는 발화만(기본, 분류기가 점수 단계를 대신하는 경우), all: 신호 있는 발화까지(분류기가 규칙 전체를 대신하는 경우)")
    args = ap.parse_args()
    run(load_rows(args.features, args.label), args.out, population=args.population)
    print("\n저장: %s/report.md, %s/oof_predictions.csv" % (args.out, args.out))


if __name__ == "__main__":
    main()
