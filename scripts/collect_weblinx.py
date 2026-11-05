"""Download WebLINX replays and page snapshots into data/cache/weblinx."""

import argparse
from pathlib import Path

from ugcguard.measure import weblinx

ap = argparse.ArgumentParser()
ap.add_argument("--cache", default="data/cache/weblinx")
ap.add_argument("--demos", type=int, default=2337)
ap.add_argument("--max-pages", type=int, default=8)
ap.add_argument("--workers", type=int, default=8)
args = ap.parse_args()
refs = weblinx.collect(Path(args.cache), args.demos, args.max_pages, workers=args.workers)
print(f"collected {len(refs)} pages from {len({r.demo for r in refs})} demos")
