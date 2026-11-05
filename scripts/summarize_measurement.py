"""Turn the per-page / per-step records into the prevalence tables in the README.

Inputs   data/cache/weblinx_pages.jsonl, data/cache/mind2web_steps.jsonl (per-page records stay
         out of git: WebLINX is CC BY-NC-SA 4.0, so only aggregate statistics are published)
Outputs  results/measurement.json, results/measurement.md
"""

import json
from collections import defaultdict
from pathlib import Path

from ugcguard.measure.categories import category

MIN_CLF_TEXT = 80  # classifier regions must hold at least this much text to count


def flags(r: dict) -> dict:
    markup = r["markup_item_body"] > 0 or r["rel_ugc_links"] > 0
    rules = markup or bool(r["signature_vendors"])
    clf = r.get("ugc_text_clf", 0) >= MIN_CLF_TEXT
    return {"markup": markup, "rules": rules, "clf": clf, "any": rules or clf}


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def weblinx(path: Path) -> dict:
    with open(path) as fh:
        recs = [json.loads(line) for line in fh]
    n = len(recs)
    out: dict = {
        "pages": n,
        "demos": len({r["demo"] for r in recs}),
        "websites": len({r["website"] for r in recs}),
    }
    f = [flags(r) for r in recs]
    for k in ("markup", "rules", "clf", "any"):
        out[f"pages_with_ugc_{k}_pct"] = pct(sum(x[k] for x in f), n)
    # Coverage: of pages where anything found UGC, how many carried standard markup?
    anyp = [(r, x) for r, x in zip(recs, f, strict=True) if x["any"]]
    out["markup_coverage_pct"] = pct(sum(x["markup"] for _, x in anyp), len(anyp))
    out["rules_coverage_pct"] = pct(sum(x["rules"] for _, x in anyp), len(anyp))
    out["jsonld_only_pages"] = sum(
        1 for r in recs if r["jsonld_ugc_objects"] > 0 and r["jsonld_anchored"] == 0
    )
    share = [r.get("ugc_text_all", r["ugc_text_rules"]) / max(r["text_len"], 1) for r, _ in anyp]
    out["ugc_text_share_median_pct"] = (
        round(100 * sorted(share)[len(share) // 2], 1) if share else 0
    )
    # Demos (tasks) that touched at least one UGC page.
    by_demo = defaultdict(lambda: {"markup": False, "rules": False, "any": False})
    for r, x in zip(recs, f, strict=True):
        for k in ("markup", "rules", "any"):
            by_demo[r["demo"]][k] |= x[k]
    out["demos_touching_ugc_markup_pct"] = pct(
        sum(v["markup"] for v in by_demo.values()), len(by_demo)
    )
    out["demos_touching_ugc_rules_pct"] = pct(
        sum(v["rules"] for v in by_demo.values()), len(by_demo)
    )
    out["demos_touching_ugc_any_pct"] = pct(sum(v["any"] for v in by_demo.values()), len(by_demo))
    # Actions.
    acts = [(a, x) for r, x in zip(recs, f, strict=True) for a in r["actions"]]
    out["actions"] = len(acts)
    out["actions_on_ugc_pages_any_pct"] = pct(sum(x["any"] for _, x in acts), len(acts))
    located = [a for a, _ in acts if a.get("found")]
    out["actions_located"] = len(located)
    out["actions_targeting_ugc_rules_pct"] = pct(
        sum(a.get("in_rules", False) for a in located), len(located)
    )
    out["actions_targeting_ugc_any_pct"] = pct(
        sum(a.get("in_rules", False) or a.get("in_clf", False) for a in located), len(located)
    )
    # Per website (macro) and per category.
    by_site = defaultdict(list)
    by_cat = defaultdict(list)
    for r, x in zip(recs, f, strict=True):
        by_site[r["website"]].append(x)
        by_cat[category(r["site"], r["url"])].append(x)
    out["websites_with_any_ugc_page_pct"] = pct(
        sum(any(x["any"] for x in xs) for xs in by_site.values()), len(by_site)
    )
    out["websites_with_markup_pct"] = pct(
        sum(any(x["markup"] for x in xs) for xs in by_site.values()), len(by_site)
    )
    out["macro_pages_with_ugc_any_pct"] = round(
        sum(pct(sum(x["any"] for x in xs), len(xs)) for xs in by_site.values()) / len(by_site), 1
    )
    out["by_category"] = {
        c: {
            "pages": len(xs),
            "markup_pct": pct(sum(x["markup"] for x in xs), len(xs)),
            "rules_pct": pct(sum(x["rules"] for x in xs), len(xs)),
            "any_pct": pct(sum(x["any"] for x in xs), len(xs)),
        }
        for c, xs in sorted(by_cat.items(), key=lambda kv: -len(kv[1]))
    }
    src = defaultdict(int)
    for r in recs:
        for s in r["markup_sources"]:
            src["markup:" + s] += 1
        for v in r["signature_vendors"]:
            src["signature:" + v] += 1
    out["pages_by_source"] = dict(sorted(src.items(), key=lambda kv: -kv[1]))
    return out


def mind2web(path: Path) -> dict:
    with open(path) as fh:
        recs = [json.loads(line) for line in fh]
    n = len(recs)
    f = [flags(r) for r in recs]
    out: dict = {
        "steps": n,
        "tasks": len({r["annotation_id"] for r in recs}),
        "websites": len({r["website"] for r in recs}),
    }
    for k in ("rules", "clf", "any"):
        out[f"steps_on_ugc_pages_{k}_pct"] = pct(sum(x[k] for x in f), n)
    by_task = defaultdict(bool)
    for r, x in zip(recs, f, strict=True):
        by_task[r["annotation_id"]] |= x["any"]
    out["tasks_touching_ugc_any_pct"] = pct(sum(by_task.values()), len(by_task))
    located = [a for r in recs for a in r["actions"] if a.get("found")]
    out["targets_in_ugc_any_pct"] = pct(
        sum(a.get("in_rules", False) or a.get("in_clf", False) for a in located), len(located)
    )
    by_dom = defaultdict(list)
    for r, x in zip(recs, f, strict=True):
        by_dom[r["domain"]].append(x)
    out["by_domain"] = {
        d: {
            "steps": len(xs),
            "rules_pct": pct(sum(x["rules"] for x in xs), len(xs)),
            "any_pct": pct(sum(x["any"] for x in xs), len(xs)),
        }
        for d, xs in sorted(by_dom.items())
    }
    return out


def markdown(w: dict, m: dict | None) -> str:
    lines = ["# UGC on the pages web agents work on", ""]
    lines += [
        f"WebLINX: {w['pages']:,} page snapshots from {w['demos']:,} demonstrations on "
        f"{w['websites']} websites; {w['actions']:,} recorded actions.",
        "",
        "| measure | standard markup | + vendor signatures | + classifier (upper bound) |",
        "|---|---|---|---|",
        f"| pages with a UGC section | {w['pages_with_ugc_markup_pct']}% | "
        f"{w['pages_with_ugc_rules_pct']}% | {w['pages_with_ugc_any_pct']}% |",
        f"| demonstrations that touch a UGC page | {w['demos_touching_ugc_markup_pct']}% | "
        f"{w['demos_touching_ugc_rules_pct']}% | "
        f"{w['demos_touching_ugc_any_pct']}% |",
        f"| actions whose target is inside UGC | | {w['actions_targeting_ugc_rules_pct']}% | "
        f"{w['actions_targeting_ugc_any_pct']}% |",
        "",
        "Standard markup (schema.org / rel=ugc / ARIA / microformats) marks UGC on "
        f"{w['pages_with_ugc_markup_pct']}% of pages, against an audited estimate of about 8% of "
        "pages that hold UGC: it covers at most about a third of the UGC agents meet. (Against the "
        f"raw, unaudited classifier denominator the figure would be {w['markup_coverage_pct']}%.)",
        "",
        "The classifier column is an upper bound: a manual audit (results/audit.md) found that "
        "only ~16% of classifier-only detections were real UGC, which puts pages with a UGC "
        "section at roughly 8% (rules 3.7% + about 4 points from the classifier).",
        "",
        "| category | pages | markup | markup + signatures | + classifier (upper bound) |",
        "|---|---|---|---|---|",
    ]
    for c, v in w["by_category"].items():
        lines.append(
            f"| {c} | {v['pages']} | {v['markup_pct']}% | {v['rules_pct']}% | {v['any_pct']}% |"
        )
    if m:
        lines += [
            "",
            f"Mind2Web (train): {m['steps']:,} action steps in {m['tasks']:,} tasks on "
            f"{m['websites']} websites. Snapshots keep no href/itemprop/rel, so only signatures "
            "and the classifier apply.",
            "",
            f"- steps on a page with UGC: {m['steps_on_ugc_pages_rules_pct']}% (signatures), "
            f"{m['steps_on_ugc_pages_any_pct']}% (signatures + classifier)",
            f"- tasks touching a UGC page: {m['tasks_touching_ugc_any_pct']}%",
            f"- action targets inside UGC: {m['targets_in_ugc_any_pct']}%",
            "",
            "| domain | steps | signatures | + classifier |",
            "|---|---|---|---|",
        ]
        for d, v in m["by_domain"].items():
            lines.append(f"| {d} | {v['steps']} | {v['rules_pct']}% | {v['any_pct']}% |")
    return "\n".join(lines) + "\n"


def main():
    w = weblinx(Path("data/cache/weblinx_pages.jsonl"))
    mp = Path("data/cache/mind2web_steps.jsonl")
    m = mind2web(mp) if mp.exists() else None
    Path("results/measurement.json").write_text(json.dumps({"weblinx": w, "mind2web": m}, indent=2))
    Path("results/measurement.md").write_text(markdown(w, m))
    print(markdown(w, m))


if __name__ == "__main__":
    main()
