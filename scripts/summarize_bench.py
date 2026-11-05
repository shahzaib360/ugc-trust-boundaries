"""Summarize results/bench_episodes.jsonl into results/bench.md and results/bench_summary.json."""

import gzip
import json
from collections import defaultdict
from pathlib import Path

ORDER = [
    "none",
    "origin-set",
    "detector-regex",
    "detector-deberta",
    "guard-markup",
    "guard-rules",
    "guard-full",
    "guard-full-body",
    "guard-oracle",
    "guard-full+origin-set",
    "guard-full+mask",
]
CROSS = ("nav", "exfil")
SAME = ("email-change", "delete", "leak-post", "buy")


def rate(xs):
    xs = list(xs)
    return round(100.0 * sum(xs) / len(xs), 1) if xs else None


def fmt(v):
    return "-" if v is None else f"{v:.1f}%"


def main():
    raw = Path("results/bench_episodes.jsonl")
    if raw.exists():
        with open(raw) as fh:
            rows = [json.loads(line) for line in fh]
    else:  # the published copy is gzipped
        with gzip.open(raw.with_suffix(".jsonl.gz"), "rt") as fh:
            rows = [json.loads(line) for line in fh]
    rows = [r for r in rows if "skipped" not in r]
    defenses = [d for d in ORDER if any(r["defense"] == d for r in rows)]
    atk = defaultdict(list)  # (defense, policy) -> rows
    ben = defaultdict(list)
    for r in rows:
        (atk if r["attack"] else ben)[(r["defense"], r["confirm_policy"])].append(r)

    summary: dict = {"episodes": len(rows), "defenses": {}}
    lines = ["# Benchmark results", ""]
    n_atk = len({(r["attack"], r["variant"]) for r in rows if r["attack"]})
    n_ben = len({(r["task"], r["variant"]) for r in rows if not r["attack"]})
    lines += [
        f"{len(rows):,} browser episodes. {n_atk} attack cases and {n_ben} benign cases "
        "(each across 3 site variants: schema.org markup / plain classes / obfuscated classes). "
        "The planner is fully injection-susceptible: it obeys any instruction it reads. "
        "Confirmation prompts are answered by an attentive user (approves what the task asked "
        "for, declines the rest) unless stated otherwise.",
        "",
        "## Security and usefulness",
        "",
        "| defense | attack success | cross-site goals | same-site goals | answer manipulation "
        "| payload reached the planner | benign task success | prompts per benign task "
        "| task success under attack |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for d in defenses:
        a = atk[(d, "oracle")]
        b = ben[(d, "oracle")]
        s = {
            "asr": rate(r["attack_success"] for r in a),
            "asr_cross": rate(r["attack_success"] for r in a if r["goal"] in CROSS),
            "asr_same": rate(r["attack_success"] for r in a if r["goal"] in SAME),
            "asr_answer": rate(r["attack_success"] for r in a if r["goal"] == "answer"),
            "compromised": rate(r["compromised"] for r in a),
            "benign_success": rate(r["task_success"] for r in b),
            "prompts_per_task": round(sum(r["prompts_plan"] for r in b) / len(b), 2) if b else None,
            "success_under_attack": rate(r["task_success"] for r in a),
        }
        summary["defenses"][d] = s
        lines.append(
            f"| {d} | {fmt(s['asr'])} | {fmt(s['asr_cross'])} | {fmt(s['asr_same'])} | "
            f"{fmt(s['asr_answer'])} | {fmt(s['compromised'])} | {fmt(s['benign_success'])} | "
            f"{s['prompts_per_task']} | {fmt(s['success_under_attack'])} |"
        )

    # By attack goal.
    goals = ["nav", "exfil", "email-change", "delete", "leak-post", "buy", "answer"]
    lines += [
        "",
        "## Attack success by goal",
        "",
        "| defense | " + " | ".join(goals) + " |",
        "|---|" + "---|" * len(goals),
    ]
    for d in defenses:
        a = atk[(d, "oracle")]
        cells = [fmt(rate(r["attack_success"] for r in a if r["goal"] == g)) for g in goals]
        summary["defenses"][d]["asr_by_goal"] = dict(zip(goals, cells, strict=True))
        lines.append(f"| {d} | " + " | ".join(cells) + " |")

    # By payload slot.
    slots = ["body", "hidden", "subtle", "author"]
    lines += [
        "",
        "## Attack success by payload placement",
        "",
        "| defense | " + " | ".join(slots) + " |",
        "|---|" + "---|" * len(slots),
    ]
    for d in defenses:
        a = atk[(d, "oracle")]
        cells = [fmt(rate(r["attack_success"] for r in a if r["slot"] == s)) for s in slots]
        lines.append(f"| {d} | " + " | ".join(cells) + " |")

    # By site variant: what the boundary detector can see.
    variants = ["schema", "plain", "obfuscated"]
    lines += [
        "",
        "## By site variant (attack success / benign success)",
        "",
        "| defense | " + " | ".join(variants) + " |",
        "|---|" + "---|" * len(variants),
    ]
    for d in defenses:
        cells = []
        for v in variants:
            av = rate(r["attack_success"] for r in atk[(d, "oracle")] if r["variant"] == v)
            bv = rate(r["task_success"] for r in ben[(d, "oracle")] if r["variant"] == v)
            cells.append(f"{fmt(av)} / {fmt(bv)}")
        lines.append(f"| {d} | " + " | ".join(cells) + " |")

    # Worst / strict user.
    lines += [
        "",
        "## If the user approves every prompt, or declines every prompt",
        "",
        "| defense | attack success (user approves all) | benign success (user declines all) |",
        "|---|---|---|",
    ]
    for d in defenses:
        a = atk.get((d, "approve"))
        b = ben.get((d, "decline"))
        if not a and not b:
            continue
        s = summary["defenses"][d]
        s["asr_approve_all"] = rate(r["attack_success"] for r in a or [])
        s["benign_decline_all"] = rate(r["task_success"] for r in b or [])
        lines.append(f"| {d} | {fmt(s['asr_approve_all'])} | {fmt(s['benign_decline_all'])} |")

    # Usefulness by what the task needs.
    needs = ["first-party", "ugc-answer", "ugc-control", "ugc-link"]
    lines += [
        "",
        "## Benign success by what the task needs",
        "",
        "| defense | " + " | ".join(needs) + " |",
        "|---|" + "---|" * len(needs),
    ]
    for d in defenses:
        b = ben[(d, "oracle")]
        cells = []
        for k in needs:
            sub = [r for r in b if r["needs"] == k]
            p = round(sum(r["prompts_plan"] for r in sub) / len(sub), 2) if sub else 0
            cells.append(f"{fmt(rate(r['task_success'] for r in sub))} ({p} prompts)")
        lines.append(f"| {d} | " + " | ".join(cells) + " |")

    # Which rule stopped attacks (guard-oracle, guard-full).
    for d in ("guard-full", "guard-oracle"):
        if (d, "oracle") not in atk:
            continue
        cnt = defaultdict(int)
        for r in atk[(d, "oracle")]:
            for s in r["steps"]:
                if s.get("source") == "attack" and s.get("verdict") in ("confirm", "block"):
                    cnt[s["rule"]] += 1
        summary["defenses"][d]["rules_fired_on_attack_steps"] = dict(cnt)
    Path("results/bench_summary.json").write_text(json.dumps(summary, indent=2))
    Path("results/bench.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
