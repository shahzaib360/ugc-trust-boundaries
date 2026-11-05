"""Run the detectors (signatures + classifier) over every Mind2Web action step.

Writes data/cache/mind2web_steps.jsonl: one record per action step (no HTML).
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ugcguard.classifier import MODEL_PATH, SectionClassifier
from ugcguard.measure import mind2web
from ugcguard.measure.analyze import analyze_page

_CLF = None


def _init(model_path):
    global _CLF
    _CLF = SectionClassifier.load(model_path)


def _work(task):
    out = []
    for k, a in enumerate(task["actions"]):
        rec = analyze_page(
            a["raw_html"],
            None,
            [{"intent": a["op"], "target": a["target"]}],
            target_attr="backend_node_id",
            classifier=_CLF,
        )
        rec.update(
            annotation_id=task["annotation_id"],
            step=k,
            website=task["website"],
            domain=task["domain"],
            subdomain=task["subdomain"],
        )
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/cache/mind2web")
    ap.add_argument("--out", default="data/cache/mind2web_steps.jsonl")
    ap.add_argument("--model", default=str(MODEL_PATH))
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    n = 0
    with (
        open(args.out, "w") as fh,
        ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.model,)) as pool,
    ):
        for recs in pool.map(_work, mind2web.iter_cached(Path(args.cache)), chunksize=2):
            for r in recs:
                fh.write(json.dumps(r) + "\n")
                n += 1
    print(f"wrote {n} step records to {args.out}")


if __name__ == "__main__":
    main()
