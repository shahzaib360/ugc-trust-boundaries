"""Train and evaluate the page-section classifier on WebLINX blocks.

Labels are distant: blocks inside schema.org/RDFa/JSON-LD/rel=ugc/ARIA/microformat
regions are positive (protocol A); protocol B adds vendor-signature regions.
Every evaluation is grouped by website, so a site never appears in both the
training and the test fold.

Outputs
  results/classifier_eval.json           metrics
  src/ugcguard/models/section_classifier.pkl         final model (all labels, with names)
  src/ugcguard/models/section_classifier_nonames.pkl content + structure only
  data/cache/fold_models/                out-of-fold models + site->fold map
"""

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import GroupKFold

from ugcguard.classifier import MODEL_PATH, SectionClassifier


def metrics(y, p, thr):
    pred = (p >= thr).astype(int)
    pr, rc, f1, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
    return {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "avg_precision": round(float(average_precision_score(y, p)), 4),
        "threshold": thr,
        "precision": round(float(pr), 4),
        "recall": round(float(rc), 4),
        "f1": round(float(f1), 4),
    }


def best_threshold(y, p):
    best, best_t = -1.0, 0.5
    for t in np.linspace(0.05, 0.95, 37):
        pred = (p >= t).astype(int)
        _, _, f1, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
        if f1 > best:
            best, best_t = f1, round(float(t), 3)
    return best_t


def grouped_oof(X, y, g, use_names, folds=5, seed=0):
    oof = np.zeros(len(y))
    fold_of = {}
    for k, (tr, te) in enumerate(GroupKFold(folds).split(X, y, g)):
        clf = SectionClassifier.train(X[tr], y[tr], use_names=use_names, seed=seed, groups=g[tr])
        oof[te] = clf.predict_proba(X[te])
        for s in set(g[te]):
            fold_of[s] = k
    return oof, fold_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", default="data/cache/weblinx_blocks.npz")
    ap.add_argument("--out", default="results/classifier_eval.json")
    ap.add_argument("--fold-dir", default="data/cache/fold_models")
    args = ap.parse_args()
    d = np.load(args.blocks, allow_pickle=False)
    X, ym, ys, g = d["X"], d["y_markup"], d["y_sig"], d["groups"]
    report = {"blocks": int(len(X))}

    # Protocol A: markup labels only.
    a = ym >= 0
    XA, yA, gA = X[a], ym[a].astype(int), g[a]
    report["A_markup_labels"] = {
        "sites": int(len(set(gA))),
        "sites_with_positives": int(len(set(gA[yA == 1]))),
    }
    for names in (True, False):
        oof, _ = grouped_oof(XA, yA, gA, names)
        thr = best_threshold(yA, oof)
        key = "with_names" if names else "no_names"
        report["A_markup_labels"][key] = {
            "at_0.5": metrics(yA, oof, 0.5),
            "at_best": metrics(yA, oof, thr),
        }
        print("A", key, report["A_markup_labels"][key]["at_best"])

    # Independent check: model trained on markup labels, scored on vendor-signature labels
    # from sites that publish no UGC markup at all.
    marked_sites = set(gA[yA == 1])
    clf_a = SectionClassifier.train(XA, yA, use_names=True, groups=gA)
    sel = (ys >= 0) & ~np.isin(g, list(marked_sites))
    if sel.sum() and (ys[sel] == 1).any():
        p = clf_a.predict_proba(X[sel])
        report["A_check_on_signature_sites"] = metrics(ys[sel].astype(int), p, 0.5)
        report["A_check_on_signature_sites"]["sites"] = int(len(set(g[sel & (ys == 1)])))
        print("A->signatures", report["A_check_on_signature_sites"])

    # Protocol B: markup or signature labels (what the shipped model is trained on).
    yU = np.where((ym == 1) | (ys == 1), 1, np.where((ym == 0) & (ys == 0), 0, -1))
    b = yU >= 0
    XB, yB, gB = X[b], yU[b].astype(int), g[b]
    report["B_union_labels"] = {
        "sites": int(len(set(gB))),
        "sites_with_positives": int(len(set(gB[yB == 1]))),
    }
    thresholds = {}
    for names in (True, False):
        oof, fold_of = grouped_oof(XB, yB, gB, names)
        thr = best_threshold(yB, oof)
        thresholds[names] = thr
        key = "with_names" if names else "no_names"
        report["B_union_labels"][key] = {
            "at_0.5": metrics(yB, oof, 0.5),
            "at_best": metrics(yB, oof, thr),
        }
        print("B", key, report["B_union_labels"][key]["at_best"])

    # Out-of-fold models for unbiased page-level measurement.
    fold_dir = Path(args.fold_dir)
    fold_dir.mkdir(parents=True, exist_ok=True)
    fold_of = {}
    for k, (tr, te) in enumerate(GroupKFold(5).split(XB, yB, gB)):
        clf = SectionClassifier.train(
            XB[tr], yB[tr], use_names=True, threshold=thresholds[True], groups=gB[tr]
        )
        clf.save(fold_dir / f"fold{k}.pkl")
        for s in set(gB[te]):
            fold_of[str(s)] = k
    (fold_dir / "site_fold.json").write_text(json.dumps(fold_of))

    # Final models.
    final = SectionClassifier.train(
        XB,
        yB,
        use_names=True,
        threshold=thresholds[True],
        groups=gB,
        labels="markup+signature",
        data="WebLINX",
    )
    final.save(MODEL_PATH)
    nonames = SectionClassifier.train(
        XB,
        yB,
        use_names=False,
        threshold=thresholds[False],
        groups=gB,
        labels="markup+signature",
        data="WebLINX",
    )
    nonames.save(MODEL_PATH.with_name("section_classifier_nonames.pkl"))
    report["final_threshold"] = {"with_names": thresholds[True], "no_names": thresholds[False]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
