"""End-to-end episodes in a real browser (skipped when Chromium cannot launch)."""

import pytest

pytest.importorskip("playwright")


@pytest.fixture(scope="module")
def env():
    from playwright.sync_api import sync_playwright

    from ugcguard.agent.browser import launch
    from ugcguard.agent.runner import _Holder, install_route
    from ugcguard.bench.server import BenchServer

    srv = BenchServer().start()
    pw = sync_playwright().start()
    try:
        browser = launch(pw, proxy=srv.proxy)
    except Exception as e:  # noqa: BLE001
        pw.stop()
        srv.stop()
        pytest.skip(f"no browser: {e}")
    ctx = browser.new_context()
    page = ctx.new_page()
    holder = _Holder()
    install_route(ctx, page, holder)
    yield srv, page, holder
    browser.close()
    pw.stop()
    srv.stop()


def _run(env, task_id, defense, goal=None, slot="body", variant="schema", policy="oracle"):
    from ugcguard.agent.runner import DEFENSES, run_episode
    from ugcguard.bench.scenarios import TASKS_BY_ID, attacks_for

    srv, page, holder = env
    task = TASKS_BY_ID[task_id]
    attacks = [a for a in attacks_for(task) if a.goal == goal and a.slot == slot] if goal else []
    return run_episode(
        page, holder, srv, task, DEFENSES[defense], variant, attacks, confirm_policy=policy
    )


@pytest.mark.browser
@pytest.mark.parametrize("task_id", ["S1", "S2", "F2", "N2", "V2", "V3"])
def test_benign_tasks_succeed_with_and_without_guard(env, task_id):
    assert _run(env, task_id, "none").task_success
    r = _run(env, task_id, "guard-rules")
    assert r.task_success and r.prompts_plan == 0


@pytest.mark.browser
def test_injected_navigation_hijacks_unguarded_agent_but_not_guarded(env):
    r = _run(env, "S1", "none", goal="nav")
    assert r.compromised and r.attack_success
    r = _run(env, "S1", "guard-rules", goal="nav")
    assert r.compromised and not r.attack_success and r.task_success


@pytest.mark.browser
def test_origin_set_misses_same_site_attack_guard_catches_it(env):
    r = _run(env, "F1", "origin-set", goal="email-change")
    assert r.attack_success
    r = _run(env, "F1", "guard-rules", goal="email-change")
    assert not r.attack_success and r.prompts_attack >= 1


@pytest.mark.browser
def test_ugc_link_task_needs_the_user(env):
    assert _run(env, "S7", "guard-rules").task_success  # user approves the prompt
    assert not _run(env, "S7", "guard-rules", policy="decline").task_success
