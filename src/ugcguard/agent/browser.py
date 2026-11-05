"""Launching Chromium through Playwright."""

from __future__ import annotations

import glob
import os


def _fallback_executable() -> str | None:
    env = os.environ.get("UGCGUARD_CHROMIUM")
    if env:
        return env
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""), "/opt/pw-browsers"]
    for root in roots:
        if not root:
            continue
        hits = sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-linux*", "chrome")))
        if hits:
            return hits[-1]
    return None


def launch(pw, proxy: str | None = None, headless: bool = True):
    """Launch Chromium; fall back to a preinstalled binary if the bundled one is missing."""
    kwargs: dict = {"headless": headless}
    if proxy:
        # Route everything through the bench server; never leak to the real network.
        kwargs["proxy"] = {"server": proxy, "bypass": "<-loopback>"}
    try:
        return pw.chromium.launch(**kwargs)
    except Exception:
        exe = _fallback_executable()
        if not exe:
            raise
        return pw.chromium.launch(executable_path=exe, **kwargs)
