"""Run the benchmark: every task x attack x site variant x defense, in parallel browsers."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .render import VARIANTS
from .scenarios import TASKS, TASKS_BY_ID, all_attacks

_W: dict = {}


def _init(model_path: str | None, detector_dir: str | None):
    from playwright.sync_api import sync_playwright

    from ..agent.browser import launch
    from ..agent.detectors import OnnxDetector, RegexDetector
    from ..agent.runner import _Holder, install_route
    from ..classifier import SectionClassifier
    from .server import BenchServer

    srv = BenchServer().start()
    pw = sync_playwright().start()
    browser = launch(pw, proxy=srv.proxy)
    ctx = browser.new_context()
    page = ctx.new_page()
    holder = _Holder()
    install_route(ctx, page, holder)
    from ..classifier import MODEL_PATH

    model_path = model_path or MODEL_PATH
    clf = SectionClassifier.load(model_path) if Path(model_path).exists() else None
    dets = {"regex": RegexDetector()}
    if detector_dir and (Path(detector_dir) / "model.onnx").exists():
        dets["deberta"] = OnnxDetector(detector_dir)
    _W.update(srv=srv, pw=pw, browser=browser, page=page, holder=holder, clf=clf, dets=dets)


def _job(job: dict) -> dict:
    from ..agent.runner import DEFENSES, run_episode

    task = TASKS_BY_ID[job["task"]]
    defense = DEFENSES[job["defense"]]
    attacks = [a for a in all_attacks() if a.id == job["attack"]] if job.get("attack") else []
    if defense.detector and defense.detector not in _W["dets"]:
        return {"skipped": f"detector {defense.detector} unavailable", **job}
    res = run_episode(
        _W["page"],
        _W["holder"],
        _W["srv"],
        task,
        defense,
        job["variant"],
        attacks,
        gullible=True,
        confirm_policy=job["policy"],
        classifier=_W["clf"],
        detector=_W["dets"].get(defense.detector or ""),
    )
    out = asdict(res)
    out["needs"] = task.needs
    return out


def jobs(defenses: list[str], variants=VARIANTS, include_benign=True, include_attacks=True):
    from ..agent.runner import DEFENSES

    out = []
    guarded = [d for d in defenses if DEFENSES[d].guard and DEFENSES[d].guard.ugc_rules]
    for v in variants:
        if include_benign:
            for t in TASKS:
                for d in defenses:
                    out.append(
                        {
                            "task": t.id,
                            "defense": d,
                            "variant": v,
                            "attack": None,
                            "policy": "oracle",
                        }
                    )
                for d in guarded:
                    out.append(
                        {
                            "task": t.id,
                            "defense": d,
                            "variant": v,
                            "attack": None,
                            "policy": "decline",
                        }
                    )
        if include_attacks:
            for a in all_attacks():
                for d in defenses:
                    out.append(
                        {
                            "task": a.task,
                            "defense": d,
                            "variant": v,
                            "attack": a.id,
                            "policy": "oracle",
                        }
                    )
                for d in guarded:
                    out.append(
                        {
                            "task": a.task,
                            "defense": d,
                            "variant": v,
                            "attack": a.id,
                            "policy": "approve",
                        }
                    )
    return out


def run(
    out_path: str | Path,
    defenses: list[str],
    workers: int = 4,
    model_path=None,
    detector_dir=None,
    variants=VARIANTS,
    log=print,
    **kw,
) -> int:
    todo = jobs(defenses, variants, **kw)
    log(f"{len(todo)} episodes on {workers} workers")
    n = 0
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with (
        open(out_path, "w") as fh,
        ProcessPoolExecutor(
            workers, initializer=_init, initargs=(model_path, detector_dir)
        ) as pool,
    ):
        for res in pool.map(_job, todo, chunksize=8):
            fh.write(json.dumps(res) + "\n")
            n += 1
            if n % 500 == 0:
                log(f"  {n}/{len(todo)}")
    return n
