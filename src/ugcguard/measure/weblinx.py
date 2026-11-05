"""Measure UGC on the pages of WebLINX demonstrations.

WebLINX (Lu et al., ICML 2024; McGill-NLP/WebLINX-full on Hugging Face) records
2,337 demonstrations of real-world web navigation over 155 live websites. Every
browser event keeps a full DOM snapshot of the page it happened on, with all
attributes intact - so standard markup can be checked on the exact pages a web
agent works on, and the element each action targeted can be located in them.

Stage 1 (``collect``) downloads replays and a sample of distinct pages per
demonstration into a gzip cache. Stage 2 (``analyze``) runs the detectors.
"""

from __future__ import annotations

import gzip
import json
import random
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urldefrag

from ..dom import site_of
from .fetch import cached_fetch, fetch

BASE = "https://huggingface.co/datasets/McGill-NLP/WebLINX-full/resolve/main"


@dataclass
class PageRef:
    demo: str
    split: str
    file: str
    url: str
    events: list[dict] = field(default_factory=list)  # {"intent", "target"}


def load_splits(cache: Path) -> dict[str, str]:
    data = json.loads(cached_fetch(f"{BASE}/splits.json", cache / "splits.json.gz"))
    demo_split: dict[str, str] = {}
    # Several keys alias the same demos (e.g. "iid_all"); keep the most specific.
    for split in ("train", "valid", "test_iid", "test_geo", "test_cat", "test_vis", "test_web"):
        for demo in data.get(split, []):
            demo_split.setdefault(demo, split)
    return demo_split


def _as_dict(x):
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except json.JSONDecodeError:
            return {}
    return {}


def pages_from_replay(demo: str, split: str, replay: dict, max_pages: int) -> list[PageRef]:
    pages: dict[str, PageRef] = {}
    for ev in replay.get("data", []):
        if ev.get("type") != "browser":
            continue
        state = _as_dict(ev.get("state"))
        action = _as_dict(ev.get("action"))
        page_file = state.get("page")
        args = action.get("arguments") or {}
        url = ((args.get("metadata") or {}).get("url")) or ""
        if not page_file or not url.startswith(("http://", "https://")):
            continue
        key = urldefrag(url)[0]
        element = args.get("element") or {}
        target = (element.get("attributes") or {}).get("data-webtasks-id")
        intent = action.get("intent") or ""
        if key not in pages:
            if len(pages) >= max_pages:
                continue
            pages[key] = PageRef(demo, split, page_file, url)
        pages[key].events.append({"intent": intent, "target": target, "page": page_file})
    return list(pages.values())


def collect(
    cache: Path,
    n_demos: int = 500,
    max_pages: int = 10,
    seed: int = 0,
    workers: int = 8,
    log=print,
) -> list[PageRef]:
    """Download replays + page snapshots for a random sample of demonstrations."""
    cache = Path(cache)
    demo_split = load_splits(cache)
    demos = sorted(demo_split)
    random.Random(seed).shuffle(demos)
    demos = demos[:n_demos]
    refs: list[PageRef] = []

    def one(demo: str) -> list[PageRef]:
        meta_path = cache / "pages" / demo / "pages.json"
        if meta_path.exists():
            return [PageRef(**p) for p in json.loads(meta_path.read_text())]
        raw = fetch(f"{BASE}/demonstrations/{demo}/replay.json")
        replay = json.loads(raw)
        prefs = pages_from_replay(demo, demo_split[demo], replay, max_pages)
        kept = []
        for p in prefs:
            try:
                cached_fetch(
                    f"{BASE}/demonstrations/{demo}/pages/{p.file}",
                    cache / "pages" / demo / (p.file + ".gz"),
                )
                kept.append(p)
            except Exception:  # noqa: BLE001 - missing snapshot files happen
                continue
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps([p.__dict__ for p in kept]))
        return kept

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, d): d for d in demos}
        for k, fut in enumerate(as_completed(futs), 1):
            try:
                refs.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                log(f"[weblinx] {futs[fut]}: {e}")
            if k % 25 == 0:
                log(f"[weblinx] {k}/{len(demos)} demos, {len(refs)} pages")
    return refs


def load_cached(cache: Path) -> list[PageRef]:
    refs = []
    for meta in sorted((Path(cache) / "pages").glob("*/pages.json")):
        refs.extend(PageRef(**p) for p in json.loads(meta.read_text()))
    return refs


def read_page(cache: Path, ref: PageRef) -> str:
    with gzip.open(Path(cache) / "pages" / ref.demo / (ref.file + ".gz"), "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def websites(refs: Iterable[PageRef]) -> dict[str, str]:
    """demo -> its main website (most frequent registrable domain)."""
    counts: dict[str, dict[str, int]] = {}
    for r in refs:
        c = counts.setdefault(r.demo, {})
        s = site_of(r.url)
        c[s] = c.get(s, 0) + 1 + len(r.events)
    return {d: max(c, key=c.get) for d, c in counts.items()}
