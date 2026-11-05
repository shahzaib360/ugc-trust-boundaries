"""Sample real, on-topic review and comment text for the benchmark sites.

Sources (downloaded from Hugging Face into data/cache/corpora):
  fancyzhx/amazon_polarity (test split) - product reviews
  google/civil_comments (test split, toxicity < 0.1) - news comments
Output: src/ugcguard/bench/data/ugc_corpus.json
"""

import json
import random
import re

import pyarrow.parquet as pq

rng = random.Random(7)
URL = re.compile(r"https?://|www\.|\.com\b", re.I)


def ok(text, lo=90, hi=420):
    return lo <= len(text) <= hi and not URL.search(text)


amazon = pq.read_table("data/cache/corpora/amazon_test.parquet").to_pylist()
topics = {
    "headphones": r"\b(headphones?|earbuds?|headset)\b",
    "kettle": r"\b(kettle|tea ?pot)\b",
    "backpack": r"\b(backpack|day ?pack|rucksack)\b",
    "lamp": r"\b(desk lamp|lamp|light bulb|led light)\b",
}
out = {"reviews": {}, "comments": {}, "sources": {}}
for name, pat in topics.items():
    rx = re.compile(pat, re.I)
    pool = [r for r in amazon if rx.search(r["content"]) and ok(r["content"])]
    rng.shuffle(pool)
    out["reviews"][name] = [
        {"title": r["title"], "body": r["content"], "stars": 5 if r["label"] == 1 else 2}
        for r in pool[:24]
    ]
civil = pq.read_table("data/cache/corpora/civil_test.parquet").to_pylist()
comment_topics = {
    "bike-lanes": r"\b(bike|bikes|cyclists?|bicycle|traffic|road|commute)\b",
    "library": r"\b(library|libraries|books?|reading|school)\b",
}
for name, pat in comment_topics.items():
    rx = re.compile(pat, re.I)
    pool = [c for c in civil if c["toxicity"] < 0.1 and rx.search(c["text"]) and ok(c["text"])]
    rng.shuffle(pool)
    out["comments"][name] = [c["text"] for c in pool[:24]]
out["sources"] = {
    "reviews": "fancyzhx/amazon_polarity (test split) on Hugging Face",
    "comments": "google/civil_comments (test split, toxicity < 0.1) on Hugging Face",
}
with open("src/ugcguard/bench/data/ugc_corpus.json", "w") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False)
print(
    {k: len(v) for k, v in out["reviews"].items()}, {k: len(v) for k, v in out["comments"].items()}
)
