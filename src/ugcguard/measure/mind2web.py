"""Measure UGC on the pages of Mind2Web tasks.

Mind2Web (Deng et al., NeurIPS 2023; osunlp/Mind2Web on Hugging Face) has 2,350
tasks on 137 real websites; its public training split (1,009 tasks, 73 sites)
stores a DOM snapshot for every action step. Those snapshots keep only a few
attributes (class, id, role, aria-label, ...): links' ``href``, ``itemprop``,
``rel`` and scripts are stripped. So on Mind2Web only vendor signatures and the
classifier can see UGC - which is exactly the "no markup" setting the
classifier is for.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path

BASE = "https://huggingface.co/datasets/osunlp/Mind2Web/resolve/main/data/train"
FILES = [f"train_{i}.json" for i in range(11)]


def collect(cache: Path, files=FILES, log=print) -> int:
    """Stream the training shards and cache each task's snapshots (gzip JSON)."""
    import urllib.request

    import ijson

    from .fetch import UA

    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    n = 0
    for fname in files:
        done = cache / f".{fname}.done"
        if done.exists():
            continue
        req = urllib.request.Request(f"{BASE}/{fname}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            for task in ijson.items(resp, "item"):
                acts = []
                for a in task["actions"]:
                    pos = a.get("pos_candidates") or []
                    acts.append(
                        {
                            "uid": a["action_uid"],
                            "op": (a.get("operation") or {}).get("op"),
                            "target": pos[0].get("backend_node_id") if pos else None,
                            "raw_html": a["raw_html"],
                        }
                    )
                rec = {
                    "annotation_id": task["annotation_id"],
                    "website": task["website"],
                    "domain": task["domain"],
                    "subdomain": task["subdomain"],
                    "task": task["confirmed_task"],
                    "actions": acts,
                }
                path = cache / f"{task['annotation_id']}.json.gz"
                with gzip.open(path, "wt", encoding="utf-8") as fh:
                    json.dump(rec, fh)
                n += 1
        done.touch()
        log(f"[mind2web] {fname} done ({n} tasks so far)")
    return n


def iter_cached(cache: Path) -> Iterator[dict]:
    for path in sorted(Path(cache).glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            yield json.load(fh)
