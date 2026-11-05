"""Run benchmark episodes with a real model instead of the scripted worst-case planner.

Works with any OpenAI-compatible /chat/completions endpoint (OpenAI, vLLM, Ollama,
llama.cpp server, a gateway in front of another provider):

    export LLM_BASE_URL=http://localhost:11434/v1  LLM_MODEL=qwen2.5:7b-instruct
    python scripts/run_llm.py --tasks S1,F1,N1 --goals nav,email-change --defenses none,guard-rules

Prompts the guard raises are answered with --policy (default: decline, i.e. a cautious
user). Results are appended to results/llm_episodes.jsonl. The published results in
results/bench.md use the scripted planner, not this script.
"""

import argparse
import json
import os
from dataclasses import asdict

from playwright.sync_api import sync_playwright

from ugcguard.agent.browser import launch
from ugcguard.agent.planners import LLMPlanner
from ugcguard.agent.runner import DEFENSES, _Holder, install_route, run_episode
from ugcguard.bench.scenarios import TASKS_BY_ID, attacks_for
from ugcguard.bench.server import BenchServer
from ugcguard.bench.world import USER
from ugcguard.classifier import default_classifier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="S1,F1,N1,V1")
    ap.add_argument("--goals", default="none,nav,email-change,leak-post")
    ap.add_argument("--slots", default="body,subtle")
    ap.add_argument("--defenses", default="none,guard-full")
    ap.add_argument("--variant", default="schema")
    ap.add_argument("--policy", default="decline")
    ap.add_argument("--out", default="results/llm_episodes.jsonl")
    args = ap.parse_args()
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ["LLM_MODEL"]
    key = os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    clf = default_classifier()
    srv = BenchServer().start()
    with sync_playwright() as pw, open(args.out, "a") as out:
        browser = launch(pw, proxy=srv.proxy)
        ctx = browser.new_context()
        page = ctx.new_page()
        holder = _Holder()
        install_route(ctx, page, holder)
        for tid in args.tasks.split(","):
            task = TASKS_BY_ID[tid]
            cases = []
            for goal in args.goals.split(","):
                if goal == "none":
                    cases.append([])
                    continue
                for slot in args.slots.split(","):
                    atk = [a for a in attacks_for(task) if a.goal == goal and a.slot == slot]
                    if atk:
                        cases.append(atk)
            for attacks in cases:
                for d in args.defenses.split(","):
                    planner = LLMPlanner(task.instruction, USER, base, model, key)
                    r = run_episode(
                        page,
                        holder,
                        srv,
                        task,
                        DEFENSES[d],
                        args.variant,
                        attacks,
                        confirm_policy=args.policy,
                        classifier=clf,
                        planner=planner,
                        max_steps=15,
                    )
                    rec = asdict(r) | {"model": model}
                    out.write(json.dumps(rec) + "\n")
                    out.flush()
                    print(
                        f"{tid} {r.attack or '-':28s} {d:14s} task={r.task_success} "
                        f"attack={r.attack_success}"
                    )
        browser.close()
    srv.stop()


if __name__ == "__main__":
    main()
