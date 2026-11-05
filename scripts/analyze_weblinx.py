"""Run the UGC detectors over every cached WebLINX page.

Writes
  data/cache/weblinx_pages.jsonl  one record per page (no HTML; kept out of git, see README)
  data/cache/weblinx_blocks.npz  block-level features + labels for the classifier
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ugcguard.classifier import SectionClassifier
from ugcguard.dom import site_of
from ugcguard.measure import weblinx
from ugcguard.measure.analyze import analyze_page

_CLF = None
_FOLDS: dict = {}
_SITE_FOLD: dict = {}


def _init(model_path, fold_dir):
    global _CLF
    _CLF = SectionClassifier.load(model_path) if model_path else None
    if fold_dir:
        fold_dir = Path(fold_dir)
        _SITE_FOLD.update(json.loads((fold_dir / "site_fold.json").read_text()))
        for p in sorted(fold_dir.glob("fold*.pkl")):
            _FOLDS[int(p.stem[4:])] = SectionClassifier.load(p)


def _work(args):
    cache, ref, examples = args
    html = weblinx.read_page(cache, ref)
    clf = _CLF
    if _FOLDS:
        # Out-of-fold model: this page's website was never seen in training.
        clf = _FOLDS[_SITE_FOLD.get(site_of(ref.url), 0)]
    rec = analyze_page(html, ref.url, ref.events, classifier=clf, examples=examples)
    rec.update(demo=ref.demo, split=ref.split, file=ref.file, site=site_of(ref.url))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/cache/weblinx")
    ap.add_argument("--out", default="data/cache/weblinx_pages.jsonl")
    ap.add_argument("--blocks", default="data/cache/weblinx_blocks.npz")
    ap.add_argument("--model", default=None, help="classifier to apply (optional)")
    ap.add_argument("--fold-dir", default=None, help="apply out-of-fold models instead")
    ap.add_argument("--no-examples", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    cache = Path(args.cache)
    refs = weblinx.load_cached(cache)
    main_site = weblinx.websites(refs)
    print(f"{len(refs)} pages from {len({r.demo for r in refs})} demos")
    examples = not args.no_examples
    Xs, ym, ys, groups = [], [], [], []
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with (
        open(args.out, "w") as out,
        ProcessPoolExecutor(
            args.workers, initializer=_init, initargs=(args.model, args.fold_dir)
        ) as pool,
    ):
        jobs = [(cache, r, examples) for r in refs]
        for rec in pool.map(_work, jobs, chunksize=4):
            rec["website"] = main_site.get(rec["demo"], rec["site"])
            if "_X" in rec:
                X = rec.pop("_X")
                Xs.append(X)
                ym.append(rec.pop("_y_markup"))
                ys.append(rec.pop("_y_sig"))
                groups.extend([rec["site"]] * len(X))
            out.write(json.dumps(rec) + "\n")
            n += 1
            if n % 500 == 0:
                print(f"  {n}/{len(refs)}")
    if examples and Xs:
        np.savez_compressed(
            args.blocks,
            X=np.concatenate(Xs).astype(np.float32),
            y_markup=np.concatenate(ym),
            y_sig=np.concatenate(ys),
            groups=np.array(groups),
        )
    print(f"wrote {n} page records to {args.out}")


if __name__ == "__main__":
    main()
