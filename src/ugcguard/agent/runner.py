"""Run one agent episode in a real browser against the benchmark sites."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..bench.scenarios import Attack, Task
from ..bench.server import BenchServer
from ..bench.world import USER
from ..dom import origin_of
from . import observe
from .detectors import strip_flagged
from .guard import ALLOW, BLOCK, CONFIRM, Action, Decision, Guard, GuardConfig, TaskScope, norm_url


@dataclass(frozen=True)
class Defense:
    name: str
    guard: GuardConfig | None = None
    sources: tuple[str, ...] = ()  # how UGC regions are found
    granularity: str = "item"
    mask: bool = False
    detector: str | None = None  # "regex" | "deberta"


FULL = ("markup", "signature", "classifier")
DEFENSES: dict[str, Defense] = {
    d.name: d
    for d in [
        Defense("none"),
        Defense("origin-set", GuardConfig(ugc_rules=False, origin_set=True)),
        Defense("detector-regex", detector="regex"),
        Defense("detector-deberta", detector="deberta"),
        Defense("guard-markup", GuardConfig(), ("markup",)),
        Defense("guard-rules", GuardConfig(), ("markup", "signature")),
        Defense("guard-full", GuardConfig(), FULL),
        Defense("guard-full-body", GuardConfig(), FULL, granularity="body"),
        Defense("guard-oracle", GuardConfig(), ("oracle",)),
        Defense("guard-full+origin-set", GuardConfig(origin_set=True), FULL),
        Defense("guard-full+mask", GuardConfig(), FULL, mask=True),
    ]
}


@dataclass
class EpisodeResult:
    task: str
    variant: str
    defense: str
    attack: str | None
    goal: str | None
    slot: str | None
    confirm_policy: str
    task_success: bool
    attack_success: bool | None
    compromised: bool
    answer: str | None
    steps: list[dict] = field(default_factory=list)
    prompts_plan: int = 0
    prompts_attack: int = 0
    blocked_plan: int = 0
    blocked_attack: int = 0
    network_blocks: int = 0
    seconds: float = 0.0


class _Holder:
    guard: Guard | None = None
    blocked: list[str]

    def __init__(self):
        self.blocked = []


def install_route(context, page, holder: _Holder) -> None:
    """R7 at the network layer: unexpected cross-origin top-level navigations are aborted."""

    def handler(route):
        req = route.request
        g = holder.guard
        if g is not None and req.is_navigation_request() and req.frame == page.main_frame:
            current = origin_of(page.url) if page.url.startswith("http") else ""
            if not g.allow_navigation(req.url, current):
                holder.blocked.append(req.url)
                return route.abort("blockedbyclient")
        return route.continue_()

    context.route("**/*", handler)


def _targets(action: Action, obs: observe.Observation) -> set[str]:
    if action.kind == "goto" and action.url:
        return {norm_url(action.url)}
    el = obs.element(action.element or "") if action.element else None
    if el is None:
        return set()
    if el.kind == "link" and el.href:
        return {norm_url(el.href)}
    if el.kind == "button" and el.form_action:
        return {norm_url(el.form_action)}
    return set()


def _execute(page, action: Action) -> tuple[bool, str]:
    try:
        if action.kind == "click":
            page.locator(f'[data-ug="{action.element}"]').first.click(timeout=4000)
            page.wait_for_load_state("load", timeout=8000)
        elif action.kind == "type":
            page.locator(f'[data-ug="{action.element}"]').first.fill(
                action.text or "", timeout=4000
            )
        elif action.kind == "goto":
            page.goto(action.url or "", timeout=8000)
        return True, ""
    except Exception as e:  # noqa: BLE001 - any browser failure ends the step
        return False, str(e).splitlines()[0][:200]


def _confirm(policy: str, action: Action) -> bool:
    if policy == "approve":
        return True
    if policy == "decline":
        return False
    return action.source == "plan"  # "oracle": an attentive user approves only what they asked


def snapshot(page, defense: Defense, classifier=None) -> observe.Observation:
    page.evaluate(observe.TAG_JS)
    html = page.content()
    return observe.build(
        html,
        page.url,
        page.title(),
        sources=defense.sources,
        granularity=defense.granularity,
        mask=defense.mask,
        classifier=classifier,
    )


def run_episode(
    page,
    holder: _Holder,
    server: BenchServer,
    task: Task,
    defense: Defense,
    variant: str,
    attacks: list[Attack] = (),
    gullible: bool = True,
    confirm_policy: str = "oracle",
    classifier=None,
    detector=None,
    planner=None,
    max_steps: int = 25,
) -> EpisodeResult:
    from .planners import ScriptedPlanner

    t0 = time.time()
    state = server.reset(variant, [a.injection for a in attacks])
    extra = task.origins if (defense.guard and defense.guard.origin_set) else ()
    scope = TaskScope.infer(task.instruction, task.start_url, USER, extra_origins=extra)
    guard = Guard(scope, defense.guard) if defense.guard else None
    holder.guard, holder.blocked = guard, []
    if planner is None:
        planner = ScriptedPlanner(task.plan, USER, list(attacks), gullible=gullible)
    res = EpisodeResult(
        task.id,
        variant,
        defense.name,
        attacks[0].id if attacks else None,
        attacks[0].goal if attacks else None,
        attacks[0].slot if attacks else None,
        confirm_policy,
        False,
        None,
        False,
        None,
    )
    page.goto("about:blank")
    page.goto(task.start_url, timeout=8000)
    answer = None
    for _ in range(max_steps):
        try:
            obs = snapshot(page, defense, classifier)
        except Exception as e:  # noqa: BLE001
            res.steps.append({"error": f"snapshot: {e}"[:200]})
            break
        if guard:
            guard.observe(obs)
        view = obs
        if defense.detector and detector is not None:
            view = snapshot(page, defense, classifier)
            strip_flagged(view, detector)
        action = planner.next(view, view.text)
        if action.kind == "stop":
            break
        targets = _targets(action, obs)
        d = guard.check(action, obs) if guard else Decision(ALLOW, answer=action.text)
        approved = None
        if d.verdict == CONFIRM:
            approved = _confirm(confirm_policy, action)
            if action.source == "attack":
                res.prompts_attack += 1
            else:
                res.prompts_plan += 1
        allowed = d.verdict == ALLOW or (d.verdict == CONFIRM and approved)
        if d.verdict == BLOCK or (d.verdict == CONFIRM and not approved):
            if action.source == "attack":
                res.blocked_attack += 1
            else:
                res.blocked_plan += 1
        step = {
            "kind": action.kind,
            "source": action.source,
            "verdict": d.verdict,
            "rule": d.rule,
            "approved": approved,
            "url": page.url,
            "target": action.note or action.url,
        }
        if action.kind == "answer":
            if allowed:
                answer = d.answer if d.answer is not None else action.text
            res.steps.append(step)
            break
        ok, err = False, "refused"
        if allowed:
            if guard:
                guard.expect_nav = targets
            n_blocked = len(holder.blocked)
            ok, err = _execute(page, action)
            if len(holder.blocked) > n_blocked:
                ok, err = False, "network: blocked navigation"
        step["ok"], step["err"] = ok, err
        res.steps.append(step)
        planner.done(ok, obs, action)
    res.answer = answer
    res.network_blocks = len(holder.blocked)
    res.compromised = bool(getattr(planner, "compromised", False))
    res.task_success = bool(task.success(state, answer))
    if attacks:
        res.attack_success = any(a.success(state, answer) for a in attacks)
    res.seconds = round(time.time() - t0, 2)
    holder.guard = None
    return res
