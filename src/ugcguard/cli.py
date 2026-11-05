"""Command line: ``ugcguard regions``, ``ugcguard demo``, ``ugcguard bench``."""

from __future__ import annotations

import argparse
import sys


def cmd_regions(args) -> int:
    from .detect import detect
    from .dom import Doc

    if args.file == "-":
        html = sys.stdin.read()
    else:
        with open(args.file, encoding="utf-8") as fh:
            html = fh.read()
    doc = Doc.from_html(html, args.url)
    rm = detect(doc, tuple(args.sources.split(",")))
    print(f"{len(rm.regions)} regions, {rm.ugc_text_len()} of {doc.page_text_len} chars of text")
    for r in rm.regions:
        text = doc.text(r.node, limit=90).replace("\n", " ")
        print(f"  {r.source:24s} {r.scope:5s} {r.ugc_type:8s} <{doc.tag[r.node]}> {text!r}")
    return 0


def cmd_demo(args) -> int:
    from playwright.sync_api import sync_playwright

    from .agent.browser import launch
    from .agent.runner import DEFENSES, _Holder, install_route, run_episode
    from .bench.scenarios import TASKS_BY_ID, attacks_for
    from .bench.server import BenchServer

    task = TASKS_BY_ID[args.task]
    attacks = [a for a in attacks_for(task) if a.goal == args.goal and a.slot == args.slot]
    srv = BenchServer().start()
    try:
        with sync_playwright() as pw:
            browser = launch(pw, proxy=srv.proxy)
            ctx = browser.new_context()
            page = ctx.new_page()
            holder = _Holder()
            install_route(ctx, page, holder)
            print(f"task: {task.instruction}")
            if attacks:
                print(f"attack: {attacks[0].id} - payload in a {task.section} on {task.ugc_page}")
            for name in args.defenses.split(","):
                r = run_episode(page, holder, srv, task, DEFENSES[name], args.variant, attacks)
                print(f"\n== defense: {name} (site variant: {args.variant})")
                for s in r.steps:
                    verdict = s["verdict"] + (f" [{s['rule']}]" if s["rule"] else "")
                    if s.get("approved") is not None:
                        verdict += " -> user " + ("approved" if s["approved"] else "declined")
                    print(
                        f"  {s['source']:6s} {s['kind']:6s} {str(s['target'])[:60]:60s} {verdict}"
                    )
                print(f"  task done: {r.task_success}   attack succeeded: {r.attack_success}")
                if r.answer:
                    print(f"  answer: {r.answer[:160]}")
            browser.close()
    finally:
        srv.stop()
    return 0


def cmd_bench(args) -> int:
    from .bench.evaluate import run

    defenses = args.defenses.split(",")
    run(
        args.out,
        defenses,
        workers=args.workers,
        model_path=args.model,
        detector_dir=args.detector,
        variants=tuple(args.variants.split(",")),
    )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ugcguard", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("regions", help="list user-generated regions in an HTML file")
    r.add_argument("file", help="HTML file, or - for stdin")
    r.add_argument("--url", default=None)
    r.add_argument("--sources", default="markup,signature,classifier")
    r.set_defaults(fn=cmd_regions)

    d = sub.add_parser("demo", help="run one benchmark episode and print the trace")
    d.add_argument("--task", default="S1")
    d.add_argument("--goal", default="nav")
    d.add_argument("--slot", default="body")
    d.add_argument("--variant", default="schema")
    d.add_argument("--defenses", default="none,origin-set,guard-rules")
    d.set_defaults(fn=cmd_demo)

    b = sub.add_parser("bench", help="run the full benchmark")
    b.add_argument("--out", default="results/bench_episodes.jsonl")
    b.add_argument(
        "--defenses",
        default="none,origin-set,detector-regex,detector-deberta,"
        "guard-markup,guard-rules,guard-full,guard-full-body,guard-oracle,"
        "guard-full+origin-set,guard-full+mask",
    )
    b.add_argument("--variants", default="schema,plain,obfuscated")
    b.add_argument("--workers", type=int, default=4)
    b.add_argument("--model", default=None, help="section classifier (default: bundled)")
    b.add_argument("--detector", default="data/cache/models/pi-deberta")
    b.set_defaults(fn=cmd_bench)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
